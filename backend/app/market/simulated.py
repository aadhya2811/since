"""Deterministic simulated market feed.

Purpose
* Tests: same numbers every run, no network.
* Demo/fallback: if Yahoo is unreachable the app keeps working and *says* it
  is on simulated data rather than showing a blank screen.

Each symbol gets a geometric-Brownian daily series seeded by its ticker, with
the volatility from the universe table so a PSU bank looks jumpier than an
FMCG name. A few scripted events are layered on recent sessions so a fresh
demo has something worth surfacing. During market hours the quote drifts
minute by minute (also deterministic) so refreshes visibly change.
"""
from __future__ import annotations

import hashlib
import math
import random
from datetime import date, datetime, timedelta

from ..util import utcnow
from . import calendar as cal
from .provider import BarData, MarketDataProvider, ProviderError, QuoteData, SymbolNotFound
from .universe import BY_SYMBOL, SymbolInfo

# (sessions_ago, daily_return, volume_multiple) — layered on the generated series.
# sessions_ago=0 is the most recent completed session.
EVENTS: dict[str, list[tuple[int, float, float]]] = {
    "TMPV.NS": [(2, 0.008, 1.0), (1, 0.004, 0.9), (0, -0.058, 3.1)],  # sharp drop on heavy volume
    "INDUSINDBK.NS": [(1, -0.041, 2.4), (0, -0.012, 1.6)],
    "HAL.NS": [(2, 0.031, 1.8), (1, 0.022, 1.5), (0, 0.018, 1.7)],  # grinding to a 52w high
    "BAJFINANCE.NS": [(0, 0.046, 2.6)],
    "ETERNAL.NS": [(3, 0.052, 2.0), (0, -0.034, 1.9)],
    "SUZLON.NS": [(0, 0.071, 3.5)],
    "ITC.NS": [],                                   # deliberately boring
}

_SESSION_MINUTES = (15 * 60 + 30) - (9 * 60 + 15)


def _seed(*parts: object) -> int:
    h = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return int(h[:16], 16)


def _info(symbol: str) -> SymbolInfo:
    if symbol in BY_SYMBOL:
        return BY_SYMBOL[symbol]
    # Unknown ticker: still simulate something plausible so search-by-typing works.
    rng = random.Random(_seed("unknown", symbol))
    return SymbolInfo(symbol, symbol.split(".")[0].title(), "Unknown", rng.uniform(80, 3000), 0.28)


def _sessions_ending(last: date, n: int) -> list[date]:
    out: list[date] = []
    d = last
    while len(out) < n:
        if cal.is_trading_day(d):
            out.append(d)
        d -= timedelta(days=1)
    return list(reversed(out))


class SimulatedProvider(MarketDataProvider):
    name = "simulated"

    def __init__(self, history_days: int = 400, *, fail: bool = False):
        self.history_days = history_days
        self.fail = fail  # tests flip this to exercise the circuit breaker
        self.unknown: set[str] = set()  # tests: symbols this feed pretends not to know
        self.calls = 0

    # ------------------------------------------------------------ internals
    def _series(self, symbol: str, last_session: date) -> list[BarData]:
        info = _info(symbol)
        rng = random.Random(_seed("series", symbol))
        daily_vol = info.vol / math.sqrt(252)
        dates = _sessions_ending(last_session, self.history_days)
        n = len(dates)
        # Anchor the *end* of the series at ref_price so the numbers look right today.
        rets = [rng.gauss(0.0002, daily_vol) for _ in range(n)]
        vols = [max(0.2, rng.lognormvariate(0, 0.35)) for _ in range(n)]
        for ago, r, vm in EVENTS.get(symbol, []):
            if ago < n:
                rets[n - 1 - ago] = r
                vols[n - 1 - ago] = vm
        closes = [1.0]
        for r in rets[1:]:
            closes.append(closes[-1] * math.exp(r))
        scale = info.ref_price / closes[-1]
        closes = [c * scale for c in closes]
        base_volume = int(2_000_000 * (1500 / max(info.ref_price, 5)) ** 0.7)
        bars: list[BarData] = []
        prev = closes[0]
        for i, d in enumerate(dates):
            c = closes[i]
            drng = random.Random(_seed("bar", symbol, d.isoformat()))
            o = prev * math.exp(drng.gauss(0, daily_vol * 0.3))
            hi = max(o, c) * (1 + abs(drng.gauss(0, daily_vol * 0.4)))
            lo = min(o, c) * (1 - abs(drng.gauss(0, daily_vol * 0.4)))
            bars.append(BarData(d, round(o, 2), round(hi, 2), round(lo, 2), round(c, 2), int(base_volume * vols[i])))
            prev = c
        return bars

    def _quote_now(self, symbol: str, now: datetime) -> QuoteData:
        st = cal.market_state(now)
        info = _info(symbol)
        if st.is_open:
            # Today's session is in progress: bars end yesterday, price walks from there.
            last_completed = cal.previous_trading_day(st.session_date)
            bars = self._series(symbol, last_completed)
            prev_close = bars[-1].close
            frac = cal.session_fraction_elapsed(now)
            minute = int(frac * _SESSION_MINUTES)
            rng = random.Random(_seed("intraday", symbol, st.session_date.isoformat()))
            daily_vol = info.vol / math.sqrt(252)
            # Deterministic random walk to the current minute.
            steps = [rng.gauss(0, daily_vol / math.sqrt(_SESSION_MINUTES)) for _ in range(_SESSION_MINUTES)]
            # Scripted "today" event so an open-market demo has drama too.
            scripted_gap = {"INDUSINDBK.NS": -0.025, "SUZLON.NS": 0.03, "TMPV.NS": -0.012}
            gap = scripted_gap.get(symbol, rng.gauss(0, daily_vol * 0.3))
            # Scripted names get a calmer intraday walk so the story they were
            # scripted to tell survives the random component.
            damp = 0.3 if symbol in scripted_gap else 1.0
            path = [prev_close * math.exp(gap)]
            for s in steps[: max(minute, 1)]:
                path.append(path[-1] * math.exp(s * damp))
            price = path[-1]
            vol_mult = {"TMPV.NS": 1.4, "INDUSINDBK.NS": 2.2, "SUZLON.NS": 2.8}.get(symbol, 1.0)
            avg_vol = sum(b.volume for b in bars[-20:]) / 20
            return QuoteData(
                symbol=symbol,
                price=round(price, 2),
                as_of=now.replace(second=0, microsecond=0),
                prev_close=prev_close,
                open=round(path[0], 2),
                day_high=round(max(path), 2),
                day_low=round(min(path), 2),
                volume=int(avg_vol * frac * vol_mult),
                name=info.name,
                source=self.name,
                delay_minutes=0,
            )
        bars = self._series(symbol, st.session_date)
        last, prev = bars[-1], bars[-2]
        return QuoteData(
            symbol=symbol,
            price=last.close,
            as_of=st.last_close,
            prev_close=prev.close,
            open=last.open,
            day_high=last.high,
            day_low=last.low,
            volume=last.volume,
            name=info.name,
            source=self.name,
            delay_minutes=0,
        )

    # ------------------------------------------------------------ interface
    async def get_quotes(self, symbols: list[str]) -> dict[str, QuoteData]:
        self.calls += 1
        if self.fail:
            raise ProviderError("simulated outage")
        now = utcnow()
        return {s: self._quote_now(s, now) for s in symbols if s not in self.unknown}

    async def get_daily_bars(self, symbol: str, days: int = 365) -> list[BarData]:
        self.calls += 1
        if self.fail:
            raise ProviderError("simulated outage")
        if symbol in self.unknown:
            raise SymbolNotFound(symbol)
        st = cal.market_state(utcnow())
        last = cal.previous_trading_day(st.session_date) if st.is_open else st.session_date
        return self._series(symbol, last)[-days:]
