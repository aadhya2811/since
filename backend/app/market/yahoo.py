"""Yahoo Finance provider (v8 chart endpoint).

Free, keyless, covers NSE ("RELIANCE.NS") and BSE (".BO"). Quotes are ~15 min
delayed for Indian exchanges — we carry the exchange timestamp through so the
UI can say so rather than pretending it is live.

The chart endpoint is used for both quotes (its `meta` block) and history,
because the v7 quote endpoint now needs a cookie+crumb dance that breaks
unpredictably. One endpoint, one failure mode.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from .provider import BarData, MarketDataProvider, ProviderError, QuoteData, SymbolNotFound

log = logging.getLogger(__name__)

_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SinceWatchlist/1.0)"}


def _ts(epoch: int | float | None) -> datetime | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).replace(tzinfo=None)


class YahooProvider(MarketDataProvider):
    name = "yahoo"

    def __init__(self, timeout: float = 8.0, max_concurrency: int = 6):
        self._timeout = timeout
        self._sem = asyncio.Semaphore(max_concurrency)

    async def _chart(self, client: httpx.AsyncClient, symbol: str, rng: str, interval: str) -> dict:
        async with self._sem:
            try:
                r = await client.get(_BASE.format(symbol=symbol), params={"range": rng, "interval": interval})
            except httpx.HTTPError as e:
                raise ProviderError(f"yahoo network error for {symbol}: {e}") from e
        if r.status_code == 404:
            raise SymbolNotFound(symbol)
        if r.status_code == 429:
            raise ProviderError("yahoo rate limited")
        if r.status_code >= 400:
            raise ProviderError(f"yahoo HTTP {r.status_code} for {symbol}")
        try:
            data = r.json()["chart"]
        except (ValueError, KeyError) as e:
            raise ProviderError(f"yahoo malformed payload for {symbol}") from e
        if data.get("error"):
            code = data["error"].get("code", "")
            if code == "Not Found":
                raise SymbolNotFound(symbol)
            raise ProviderError(f"yahoo error for {symbol}: {data['error']}")
        results = data.get("result") or []
        if not results:
            raise SymbolNotFound(symbol)
        return results[0]

    async def _quote(self, client: httpx.AsyncClient, symbol: str) -> QuoteData | None:
        try:
            res = await self._chart(client, symbol, "5d", "1d")
        except SymbolNotFound:
            return None
        m = res.get("meta", {})
        price = m.get("regularMarketPrice")
        as_of = _ts(m.get("regularMarketTime"))
        if price is None or as_of is None:
            return None
        # Careful with "previous close": `chartPreviousClose` is the close before
        # the *chart range* (5 sessions ago here), not yesterday's. Derive it
        # from the daily rows: the close of the session before the print's date.
        ind = (res.get("indicators", {}).get("quote") or [{}])[0]
        ts = res.get("timestamp") or []
        opens, closes = ind.get("open") or [], ind.get("close") or []
        today_idx = next((i for i, t in enumerate(ts) if _ts(t) and _ts(t).date() == as_of.date()), None)
        prev_close = None
        today_open = None
        if today_idx is not None:
            today_open = _f(opens[today_idx]) if today_idx < len(opens) else None
            for j in range(today_idx - 1, -1, -1):
                if j < len(closes) and closes[j] is not None:
                    prev_close = float(closes[j])
                    break
        if prev_close is None:
            prev_close = _f(m.get("regularMarketPreviousClose") or m.get("previousClose"))
        return QuoteData(
            symbol=symbol,
            price=float(price),
            as_of=as_of,
            prev_close=prev_close,
            open=today_open,
            day_high=_f(m.get("regularMarketDayHigh")),
            day_low=_f(m.get("regularMarketDayLow")),
            volume=int(m["regularMarketVolume"]) if m.get("regularMarketVolume") is not None else None,
            name=m.get("longName") or m.get("shortName"),
            currency=m.get("currency") or "INR",
            source=self.name,
            # Yahoo declares its own lag per exchange. NSE is usually 15; if it
            # says 0 we take it at its word and only then call the price live.
            delay_minutes=int(m["exchangeDataDelayedBy"]) if m.get("exchangeDataDelayedBy") is not None else 15,
        )

    async def get_quotes(self, symbols: list[str]) -> dict[str, QuoteData]:
        if not symbols:
            return {}
        async with httpx.AsyncClient(timeout=self._timeout, headers=_HEADERS) as client:
            results = await asyncio.gather(*(self._quote(client, s) for s in symbols), return_exceptions=True)
        out: dict[str, QuoteData] = {}
        errors = 0
        for sym, r in zip(symbols, results):
            if isinstance(r, QuoteData):
                out[sym] = r
            elif isinstance(r, Exception):
                errors += 1
                log.warning("yahoo quote failed for %s: %s", sym, r)
        # Partial success is fine; total failure means the provider is down.
        if errors and not out:
            raise ProviderError(f"yahoo: all {errors} quote requests failed")
        return out

    async def get_daily_bars(self, symbol: str, days: int = 365) -> list[BarData]:
        rng = "1y" if days <= 366 else "2y"
        async with httpx.AsyncClient(timeout=self._timeout, headers=_HEADERS) as client:
            res = await self._chart(client, symbol, rng, "1d")
        ts = res.get("timestamp") or []
        q = (res.get("indicators", {}).get("quote") or [{}])[0]
        bars: list[BarData] = []
        for i, t in enumerate(ts):
            o, h, l, c, v = (q.get(k, [None] * len(ts))[i] for k in ("open", "high", "low", "close", "volume"))
            if None in (o, h, l, c):
                continue  # Yahoo emits null rows for holidays/halts
            bars.append(BarData(_ts(t).date(), float(o), float(h), float(l), float(c), int(v or 0)))
        # Drop today's partial bar if the market is still trading.
        from .calendar import market_state
        from ..util import utcnow

        st = market_state(utcnow())
        if st.is_open and bars and bars[-1].date == st.session_date:
            bars.pop()
        return bars[-days:]


def _f(x) -> float | None:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None
