"""Snapshot store: the only place market data is written.

Conflict rules (the "stale, delayed or conflicting data" question):
1. Market time only moves forward. A quote whose `as_of` is older than what we
   already hold is discarded — a slow response arriving after a fast one, or a
   fallback provider lagging the primary, can never rewind a price.
2. Same `as_of`, different price (two vendors disagree on the same print):
   the primary provider wins, otherwise the later fetch wins. We record which
   source produced the row so the disagreement is auditable.
3. Daily bars are upserted by (symbol, date); a re-fetch corrects a bar rather
   than duplicating it.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DailyBar, NewsItem, Quote, SymbolMeta
from ..util import utcnow
from .news import NewsData
from .provider import BarData, FundamentalsData, QuoteData
from .universe import BY_SYMBOL

log = logging.getLogger(__name__)


def ensure_symbol(db: Session, symbol: str, name: str | None = None) -> SymbolMeta:
    from .news import MARKET_TOPICS

    meta = db.get(SymbolMeta, symbol)
    if meta is None:
        info = BY_SYMBOL.get(symbol)
        topic = MARKET_TOPICS.get(symbol)
        meta = SymbolMeta(
            symbol=symbol,
            name=(topic[0] if topic else None) or name or (info.name if info else symbol),
            sector="Market" if topic else (info.sector if info else None),
        )
        db.add(meta)
        db.flush()
    elif name and meta.name == symbol:
        meta.name = name
    return meta


def upsert_quote(db: Session, q: QuoteData, *, primary_source: str | None = None) -> bool:
    """Returns True if the stored quote changed."""
    now = utcnow()
    row = db.get(Quote, q.symbol)
    if row is None:
        db.add(Quote(symbol=q.symbol, price=q.price, prev_close=q.prev_close, open=q.open, day_high=q.day_high,
                     day_low=q.day_low, volume=q.volume, as_of=q.as_of, fetched_at=now, source=q.source,
                     delay_minutes=q.delay_minutes))
        ensure_symbol(db, q.symbol, q.name)
        return True
    if q.as_of < row.as_of:
        log.debug("discarding stale %s quote from %s (%s < %s)", q.symbol, q.source, q.as_of, row.as_of)
        return False
    if q.as_of == row.as_of and q.price != row.price:
        # Same print, different number. Trust the primary; otherwise the newer fetch.
        if primary_source and row.source == primary_source and q.source != primary_source:
            return False
        log.info("quote conflict %s @%s: %s=%s vs %s=%s", q.symbol, q.as_of, row.source, row.price, q.source, q.price)
    changed = (row.price, row.volume, row.as_of) != (q.price, q.volume, q.as_of)
    row.price, row.prev_close, row.open = q.price, q.prev_close, q.open
    row.day_high, row.day_low, row.volume = q.day_high, q.day_low, q.volume
    row.as_of, row.fetched_at, row.source = q.as_of, now, q.source
    row.delay_minutes = q.delay_minutes
    if q.name:
        ensure_symbol(db, q.symbol, q.name)
    return changed


def upsert_bars(db: Session, symbol: str, bars: list[BarData]) -> int:
    if not bars:
        return 0
    existing = {
        b.date: b
        for b in db.scalars(select(DailyBar).where(DailyBar.symbol == symbol, DailyBar.date >= bars[0].date))
    }
    n = 0
    for b in bars:
        row = existing.get(b.date)
        if row is None:
            db.add(DailyBar(symbol=symbol, date=b.date, open=b.open, high=b.high, low=b.low, close=b.close, volume=b.volume))
            n += 1
        elif (row.close, row.volume) != (b.close, b.volume):
            row.open, row.high, row.low, row.close, row.volume = b.open, b.high, b.low, b.close, b.volume
            n += 1
    meta = ensure_symbol(db, symbol)
    meta.bars_refreshed_at = utcnow()
    return n


def get_bars(db: Session, symbol: str, limit: int = 300) -> list[DailyBar]:
    rows = db.scalars(
        select(DailyBar).where(DailyBar.symbol == symbol).order_by(DailyBar.date.desc()).limit(limit)
    ).all()
    return list(reversed(rows))


def get_bars_many(db: Session, symbols: list[str], limit: int = 300) -> dict[str, list[DailyBar]]:
    if not symbols:
        return {}
    rows = db.scalars(
        select(DailyBar).where(DailyBar.symbol.in_(symbols)).order_by(DailyBar.symbol, DailyBar.date)
    ).all()
    out: dict[str, list[DailyBar]] = {s: [] for s in symbols}
    for r in rows:
        out[r.symbol].append(r)
    return {s: b[-limit:] for s, b in out.items()}


def get_quotes(db: Session, symbols: list[str]) -> dict[str, Quote]:
    if not symbols:
        return {}
    return {q.symbol: q for q in db.scalars(select(Quote).where(Quote.symbol.in_(symbols)))}


def close_on_or_before(bars: list[DailyBar], d: date) -> DailyBar | None:
    """Last completed session on or before `d`."""
    for b in reversed(bars):
        if b.date <= d:
            return b
    return None


def upsert_news(db: Session, symbol: str, items: list[NewsData]) -> int:
    have = set(db.scalars(select(NewsItem.guid).where(NewsItem.symbol == symbol)))
    n = 0
    for it in items:
        if it.guid in have:
            continue
        db.add(NewsItem(symbol=symbol, guid=it.guid, title=it.title[:300], url=it.url[:600], source=it.source[:80],
                        published_at=it.published_at))
        have.add(it.guid)
        n += 1
    meta = ensure_symbol(db, symbol)
    meta.news_refreshed_at = utcnow()
    return n


def get_news_many(db: Session, symbols: list[str], since: datetime, limit_per_symbol: int = 8) -> dict[str, list[NewsItem]]:
    if not symbols:
        return {}
    rows = db.scalars(
        select(NewsItem).where(NewsItem.symbol.in_(symbols), NewsItem.published_at >= since)
        .order_by(NewsItem.symbol, NewsItem.published_at.desc())
    ).all()
    out: dict[str, list[NewsItem]] = {s: [] for s in symbols}
    for r in rows:
        if len(out[r.symbol]) < limit_per_symbol:
            out[r.symbol].append(r)
    return out


def upsert_fundamentals(db: Session, f: FundamentalsData) -> None:
    """Overwrite in place. Unlike quotes there is no monotonic-time rule here:
    a restatement is a correction, and the newest answer from the vendor is
    the one to keep."""
    from ..models import Fundamental

    row = db.get(Fundamental, f.symbol)
    if row is None:
        row = Fundamental(symbol=f.symbol)
        db.add(row)
    for field in ("market_cap", "pe_trailing", "pe_forward", "price_to_book", "eps_trailing",
                  "book_value", "roe", "dividend_yield", "debt_to_equity", "profit_margin",
                  "revenue_growth", "beta", "as_of"):
        setattr(row, field, getattr(f, field))
    row.source = f.source
    row.fetched_at = utcnow()


def get_fundamentals(db: Session, symbols: list[str]) -> dict[str, "Fundamental"]:
    from ..models import Fundamental

    if not symbols:
        return {}
    return {r.symbol: r for r in db.scalars(select(Fundamental).where(Fundamental.symbol.in_(symbols)))}
