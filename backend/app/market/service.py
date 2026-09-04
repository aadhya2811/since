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
from ..models import PriceLevel, Quote, SymbolMeta, User, Watchlist, WatchlistItem
from ..util import utcnow
from . import calendar as cal
from .news import GoogleNewsProvider, NewsProvider, SimulatedNewsProvider
from .provider import MarketDataProvider, ProviderError
from .resilient import Breaker, ResilientProvider
from .simulated import SimulatedProvider
from .store import upsert_bars, upsert_news, upsert_quote
from .yahoo import YahooProvider

log = logging.getLogger(__name__)

QUOTE_BATCH = 20
HOT_WINDOW = timedelta(minutes=15)


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
            if not tracked:
                self.last_tick_at = now
                return
            hot = self._hot_symbols(db, now)
            quotes = {q.symbol: q for q in db.scalars(select(Quote).where(Quote.symbol.in_(tracked)))}
            metas = {m.symbol: m for m in db.scalars(select(SymbolMeta).where(SymbolMeta.symbol.in_(tracked)))}

            due_quotes = []
            for s in tracked:
                q = quotes.get(s)
                interval = base if s in hot else base * 3
                if q is None or (now - q.fetched_at).total_seconds() >= interval:
                    due_quotes.append(s)

            due_bars = []
            last_completed = cal.previous_trading_day(state.session_date) if state.is_open else state.session_date
            for s in tracked:
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
                for s in tracked:
                    m = metas.get(s)
                    mins = self.settings.news_refresh_minutes * (1 if s in hot else 4)
                    if m is None or m.news_refreshed_at is None or (now - m.news_refreshed_at).total_seconds() >= mins * 60:
                        due_news.append(s)

        if due_quotes:
            await self.refresh_quotes(due_quotes)
        for s in due_bars[:10]:  # bars are heavier; spread them across ticks
            await self.refresh_bars(s)
        for s in due_news[:6]:   # news is heaviest and least urgent; trickle it
            await self.refresh_news(s)
        self.last_tick_at = now

    # ------------------------------------------------------------ fetchers
    async def refresh_quotes(self, symbols: list[str]) -> int:
        updated = 0
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
        return updated

    async def refresh_bars(self, symbol: str) -> int:
        try:
            bars = await self.provider.get_daily_bars(symbol, days=300)
        except ProviderError as e:
            self.last_error = str(e)
            log.warning("bars refresh failed for %s: %s", symbol, e)
            return 0
        with session_scope() as db:
            return upsert_bars(db, symbol, bars)

    async def refresh_news(self, symbol: str) -> int:
        """Walk the news chain with per-provider breakers. News failing is
        never fatal — the briefing simply shows fewer headlines."""
        from .universe import BY_SYMBOL

        with session_scope() as db:
            meta = db.get(SymbolMeta, symbol)
            company = meta.name if meta else (BY_SYMBOL[symbol].name if symbol in BY_SYMBOL else symbol)
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
        await self.refresh_bars(symbol)
        await self.refresh_news(symbol)
        return True

    # ------------------------------------------------------------ queries
    @staticmethod
    def _tracked_symbols(db) -> list[str]:
        a = db.scalars(select(distinct(WatchlistItem.symbol))).all()
        b = db.scalars(select(distinct(PriceLevel.symbol))).all()
        return sorted(set(a) | set(b))

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
