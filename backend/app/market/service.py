"""MarketService: owns the provider chain and the refresh loop.

Scaling shape
* The unit of work is a *symbol*, never a user. Refresh cost is
  O(distinct symbols), not O(users × watchlist size).
* Attention-tiered polling: symbols someone has looked at recently refresh
  at the base interval; symbols nobody is watching right now refresh 3× less
  often. Off-hours the whole thing slows to a trickle.
* One process today. The loop is a plain coroutine with a DB-backed
  `fetched_at` as its only state, so N workers can run it with a
  `SELECT ... FOR UPDATE SKIP LOCKED` (Postgres) or a Redis lease without
  changing the code above this file.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import distinct, func, select

from ..config import Settings
from ..db import session_scope
from ..models import Pin, PriceLevel, Quote, SymbolMeta, User, Watchlist, WatchlistItem
from ..util import utcnow
from . import calendar as cal
from .news import HEADLINE_SYMBOLS, MARKET_TOPICS, GoogleNewsProvider, NewsProvider, SimulatedNewsProvider
from .provider import MarketDataProvider, ProviderError, SymbolNotFound
from .resilient import Breaker, ResilientProvider
from .simulated import SimulatedProvider
from .store import ensure_symbol, upsert_bars, upsert_news, upsert_quote
from .yahoo import YahooProvider

log = logging.getLogger(__name__)

QUOTE_BATCH = 20
HOT_WINDOW = timedelta(minutes=15)
MISSES_BEFORE_UNAVAILABLE = 2      # consecutive "not in response" before we give up on a ticker
UNAVAILABLE_RETRY = timedelta(hours=24)


def build_provider(settings: Settings) -> ResilientProvider:
    def make(name: str) -> MarketDataProvider:
        if name == "yahoo":
            return YahooProvider(timeout=settings.provider_timeout_seconds)
        if name == "simulated":
            return SimulatedProvider()
        raise ValueError(f"unknown provider {name!r}")

    chain = [make(settings.provider)]
    if settings.fallback_provider and settings.fallback_provider != settings.provider:
        chain.append(make(settings.fallback_provider))
    return ResilientProvider(chain, settings.breaker_failure_threshold, settings.breaker_reset_seconds)


def build_news_chain(settings: Settings) -> list[NewsProvider]:
    def make(name: str) -> NewsProvider | None:
        if name == "google":
            return GoogleNewsProvider(timeout=settings.provider_timeout_seconds)
        if name == "simulated":
            return SimulatedNewsProvider()
        return None

    chain = [p for p in (make(settings.news_provider), make(settings.news_fallback_provider or "")) if p]
    # De-dupe if primary == fallback.
    seen, out = set(), []
    for p in chain:
        if p.name not in seen:
            out.append(p)
            seen.add(p.name)
    return out


class MarketService:
    def __init__(self, provider: ResilientProvider, settings: Settings, news_chain: list[NewsProvider] | None = None):
        self.provider = provider
        self.settings = settings
        self.news_chain = news_chain if news_chain is not None else []
        self.news_breakers = {p.name: Breaker(settings.breaker_failure_threshold, settings.breaker_reset_seconds)
                              for p in self.news_chain}
        self.news_active: str | None = self.news_chain[0].name if self.news_chain else None
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        # Symbols with a fetch in progress, per kind. The refresh loop, a
        # sample-list warmup and an "add symbol" can all want the same
        # ticker at the same moment; only one request goes out.
        self._inflight: dict[str, set[str]] = {"quote": set(), "bars": set(), "news": set()}
        self.last_tick_at = None
        self.last_error: str | None = None

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self.settings.scheduler_enabled and self._task is None:
            self._task = asyncio.create_task(self._loop(), name="market-refresh")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def poke(self) -> None:
        """Ask the loop to run now (e.g. a symbol was just added)."""
        self._wake.set()

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # never let the loop die
                log.exception("refresh tick failed")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=15)
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------ one pass
    async def tick(self) -> None:
        now = utcnow()
        state = cal.market_state(now)
        base = self.settings.quote_refresh_open_seconds if state.is_open else self.settings.quote_refresh_closed_seconds

        with session_scope() as db:
            tracked = self._tracked_symbols(db)
            if not tracked and not self.settings.universe_scan:
                self.last_tick_at = now
                return
            hot = self._hot_symbols(db, now)
            quotes = {q.symbol: q for q in db.scalars(select(Quote).where(Quote.symbol.in_(tracked)))} if tracked else {}
            metas = {m.symbol: m for m in db.scalars(select(SymbolMeta).where(SymbolMeta.symbol.in_(tracked)))} if tracked else {}
            metas_all = {m.symbol: m for m in db.scalars(select(SymbolMeta))}

            def skip(sym: str) -> bool:
                m = metas.get(sym)
                if m is None or not m.unavailable:
                    return False
                # Retry a dead ticker once a day in case it was a transient miss.
                return not (m.bars_refreshed_at and now - m.bars_refreshed_at > UNAVAILABLE_RETRY)

            due_quotes = []
            for s in tracked:
                if skip(s):
                    continue
                q = quotes.get(s)
                interval = base if s in hot else base * 3
                if q is None or (now - q.fetched_at).total_seconds() >= interval:
                    due_quotes.append(s)

            due_bars = []
            for s in tracked:
                if skip(s):
                    continue
                m = metas.get(s)
                if m is None or m.bars_refreshed_at is None:
                    due_bars.append(s)
                    continue
                age_h = (now - m.bars_refreshed_at).total_seconds() / 3600
                if age_h >= self.settings.bars_refresh_hours:
                    due_bars.append(s)
                elif not state.is_open and m.bars_refreshed_at < state.last_close and now >= state.last_close:
                    due_bars.append(s)  # session just closed: pick up today's completed bar

            due_news = []
            if self.news_chain:
                # Market topics and the index heavyweights are refreshed whether
                # or not anyone follows them: the News page needs them.
                for s in list(dict.fromkeys(list(MARKET_TOPICS) + HEADLINE_SYMBOLS + list(tracked))):
                    if s in tracked and skip(s):
                        continue
                    m = metas_all.get(s)
                    always = s in MARKET_TOPICS or s in HEADLINE_SYMBOLS
                    mins = self.settings.news_refresh_minutes * (1 if (s in hot or always) else 4)
                    if m is None or m.news_refreshed_at is None or (now - m.news_refreshed_at).total_seconds() >= mins * 60:
                        due_news.append(s)

            # Universe scan: bars for names nobody watches yet, a few per tick.
            due_scan: list[str] = []
            if self.settings.universe_scan:
                from .universe import UNIVERSE

                tracked_set = set(tracked)
                for info in UNIVERSE:
                    if info.symbol in tracked_set:
                        continue
                    m = metas_all.get(info.symbol)
                    if m is not None and m.unavailable:
                        continue
                    if m is None or m.bars_refreshed_at is None or (now - m.bars_refreshed_at).total_seconds() >= 20 * 3600:
                        due_scan.append(info.symbol)
                due_scan.sort(key=lambda s: not s.startswith("^"))   # indices first: the Market page leads with them

        if due_quotes:
            await self.refresh_quotes(due_quotes)
        # Bars and news are heavier; a bounded slice per tick, fetched concurrently
        # (the providers cap their own connection counts).
        await asyncio.gather(*(self.refresh_bars(s) for s in due_bars[:12]),
                             *(self.refresh_news(s) for s in due_news[:8]),
                             *(self.refresh_bars(s) for s in due_scan[:4]))
        self.last_tick_at = now

    async def warm(self, symbols: list[str]) -> None:
        """Fetch everything for a set of symbols, concurrently, deduplicated
        against whatever the loop is already doing. Used when a watchlist is
        created so the first briefing is populated within a couple of seconds
        without blocking the request that created it."""
        await self.refresh_quotes(symbols)
        await asyncio.gather(*(self.refresh_bars(s) for s in symbols))
        await asyncio.gather(*(self.refresh_news(s) for s in symbols))

    # ------------------------------------------------------------ fetchers
    async def refresh_quotes(self, symbols: list[str]) -> int:
        symbols = [s for s in symbols if s not in self._inflight["quote"]]
        if not symbols:
            return 0
        self._inflight["quote"].update(symbols)
        updated = 0
        try:
            for i in range(0, len(symbols), QUOTE_BATCH):
                batch = symbols[i : i + QUOTE_BATCH]
                try:
                    fetched = await self.provider.get_quotes(batch)
                    self.last_error = None
                except ProviderError as e:
                    self.last_error = str(e)
                    log.warning("quote refresh failed for %d symbols: %s", len(batch), e)
                    continue
                with session_scope() as db:
                    for q in fetched.values():
                        if upsert_quote(db, q, primary_source=self.provider.chain[0].name):
                            updated += 1
                        meta = ensure_symbol(db, q.symbol)
                        meta.miss_count, meta.unavailable, meta.unavailable_reason = 0, False, None
                    # The provider answered but left some symbols out: the ticker
                    # is probably wrong. Two strikes and we stop asking.
                    for s in batch:
                        if s in fetched:
                            continue
                        meta = ensure_symbol(db, s)
                        meta.miss_count = (meta.miss_count or 0) + 1
                        if meta.miss_count >= MISSES_BEFORE_UNAVAILABLE and not meta.unavailable:
                            meta.unavailable = True
                            meta.unavailable_reason = f"not found on {self.provider.active}"
                            meta.bars_refreshed_at = utcnow()
                            log.warning("marking %s unavailable (%s)", s, meta.unavailable_reason)
        finally:
            self._inflight["quote"].difference_update(symbols)
        return updated

    async def refresh_bars(self, symbol: str) -> int:
        if symbol in self._inflight["bars"]:
            return 0
        self._inflight["bars"].add(symbol)
        try:
            try:
                bars = await self.provider.get_daily_bars(symbol, days=300)
            except SymbolNotFound:
                with session_scope() as db:
                    meta = ensure_symbol(db, symbol)
                    meta.unavailable, meta.unavailable_reason = True, f"not found on {self.provider.active}"
                    meta.bars_refreshed_at = utcnow()
                log.warning("%s: symbol not found on %s — marked unavailable", symbol, self.provider.active)
                return 0
            except ProviderError as e:
                self.last_error = str(e)
                log.warning("bars refresh failed for %s: %s", symbol, e)
                return 0
            with session_scope() as db:
                return upsert_bars(db, symbol, bars)
        finally:
            self._inflight["bars"].discard(symbol)

    async def refresh_news(self, symbol: str) -> int:
        """Walk the news chain with per-provider breakers. News failing is
        never fatal — the briefing simply shows fewer headlines."""
        from .universe import BY_SYMBOL

        if symbol in self._inflight["news"] or not self.news_chain:
            return 0
        self._inflight["news"].add(symbol)
        try:
            with session_scope() as db:
                meta = db.get(SymbolMeta, symbol)
                company = (MARKET_TOPICS[symbol][0] if symbol in MARKET_TOPICS
                   else (meta.name if meta and meta.name != symbol
                         else (BY_SYMBOL[symbol].name if symbol in BY_SYMBOL else symbol)))
            return await self._fetch_news(symbol, company)
        finally:
            self._inflight["news"].discard(symbol)

    async def _fetch_news(self, symbol: str, company: str) -> int:
        for p in self.news_chain:
            br = self.news_breakers[p.name]
            if not br.allow():
                continue
            try:
                items = await p.get_news(symbol, company)
            except Exception as e:  # noqa: BLE001
                br.record_failure(e)
                log.warning("news provider %s failed for %s: %s", p.name, symbol, e)
                continue
            br.record_success()
            self.news_active = p.name
            with session_scope() as db:
                return upsert_news(db, symbol, items)
        with session_scope() as db:   # mark attempted so we don't hammer a dead source
            meta = db.get(SymbolMeta, symbol)
            if meta:
                meta.news_refreshed_at = utcnow()
        return 0

    async def ensure_symbol_data(self, symbol: str) -> bool:
        """Called when a user adds a symbol: fetch quote + history right away
        so the UI is never empty. Returns False if the symbol is unknown."""
        try:
            quotes = await self.provider.get_quotes([symbol])
        except ProviderError:
            return False
        if symbol not in quotes:
            return False
        with session_scope() as db:
            upsert_quote(db, quotes[symbol], primary_source=self.provider.chain[0].name)
            meta = ensure_symbol(db, symbol)
            meta.miss_count, meta.unavailable, meta.unavailable_reason = 0, False, None
        # History is needed for the card to make sense (σ, 52w) — one request,
        # worth waiting for. Headlines can arrive a second later.
        await self.refresh_bars(symbol)
        asyncio.ensure_future(self.refresh_news(symbol))
        return True

    # ------------------------------------------------------------ queries
    @staticmethod
    def _tracked_symbols(db) -> list[str]:
        a = db.scalars(select(distinct(WatchlistItem.symbol))).all()
        b = db.scalars(select(distinct(PriceLevel.symbol))).all()
        c = db.scalars(select(distinct(Pin.symbol))).all()
        tracked = set(a) | set(b) | set(c)
        if tracked:
            tracked.add("^NSEI")   # the market itself, for market-relative context
        return sorted(tracked)

    @staticmethod
    def _hot_symbols(db, now) -> set[str]:
        cutoff = now - HOT_WINDOW
        rows = db.execute(
            select(distinct(WatchlistItem.symbol))
            .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
            .join(User, User.id == Watchlist.user_id)
            .where(User.last_seen_at >= cutoff)
        ).scalars().all()
        return set(rows)

    def status(self) -> dict:
        return {
            **self.provider.status(),
            "news": {"active": self.news_active,
                     "providers": [{"name": p.name, "breaker": self.news_breakers[p.name].state} for p in self.news_chain]},
            "scheduler_running": self._task is not None and not self._task.done(),
            "last_tick_at": self.last_tick_at,
            "last_error": self.last_error,
        }
