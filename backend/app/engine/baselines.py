"""Per-user baselines: the answer to "since *when*?"

The baseline is the price the user last saw before they *left* — not the
last refresh, or the diff would reset itself every 30 seconds while they
sit on the page. So:

* A *visit* is a run of requests with the same client-generated visit id
  and no gap longer than `visit_idle_minutes`.
* Within a visit, every briefing records what they saw as *pending*.
* When a new visit begins, pending → committed. The briefing now diffs
  against what they last saw before leaving.
* Acknowledging a symbol commits immediately ("ok, seen it").
* Adding a symbol commits the current quote ("since you added it").
* Demo rewind commits the close of N sessions ago so a first-time viewer can
  see the feature work without waiting three days.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Baseline, DailyBar, Quote, User
from ..market import calendar as cal


def touch_visit(db: Session, user: User, visit_id: str | None, now: datetime, idle_minutes: int) -> bool:
    """Returns True if this request starts a new visit."""
    idle = user.last_seen_at is None or (now - user.last_seen_at) > timedelta(minutes=idle_minutes)
    new_visit = idle or (visit_id is not None and visit_id != user.current_visit_id)
    if new_visit:
        for b in db.scalars(select(Baseline).where(Baseline.user_id == user.id, Baseline.pending_price.is_not(None))):
            b.committed_price, b.committed_as_of, b.committed_seen_at = b.pending_price, b.pending_as_of, b.pending_seen_at
            b.pending_price = b.pending_as_of = b.pending_seen_at = None
        user.current_visit_id = visit_id
    user.last_seen_at = now
    return new_visit


def get_baselines(db: Session, user_id: int, symbols: list[str]) -> dict[str, Baseline]:
    if not symbols:
        return {}
    rows = db.scalars(select(Baseline).where(Baseline.user_id == user_id, Baseline.symbol.in_(symbols)))
    return {b.symbol: b for b in rows}


def record_seen(db: Session, user_id: int, symbol: str, quote: Quote, now: datetime, existing: Baseline | None) -> Baseline:
    if existing is None:
        b = Baseline(user_id=user_id, symbol=symbol, committed_price=quote.price, committed_as_of=quote.as_of,
                     committed_seen_at=now)
        db.add(b)
        return b
    if existing.pending_as_of is None or quote.as_of >= existing.pending_as_of:
        existing.pending_price, existing.pending_as_of, existing.pending_seen_at = quote.price, quote.as_of, now
    return existing


def acknowledge(db: Session, user_id: int, symbol: str, quote: Quote, now: datetime) -> None:
    b = db.scalar(select(Baseline).where(Baseline.user_id == user_id, Baseline.symbol == symbol))
    if b is None:
        db.add(Baseline(user_id=user_id, symbol=symbol, committed_price=quote.price, committed_as_of=quote.as_of,
                        committed_seen_at=now))
        return
    b.committed_price, b.committed_as_of, b.committed_seen_at = quote.price, quote.as_of, now
    b.pending_price = b.pending_as_of = b.pending_seen_at = None


def rewind(db: Session, user_id: int, bars_by_symbol: dict[str, list[DailyBar]], sessions: int, now: datetime,
           *, market_open: bool) -> int:
    """Pretend the user last looked at the close `sessions` sessions ago.
    Bars are completed sessions only, so while the market is open today's
    partial session counts as one of the N."""
    idx = -max(sessions, 1) if market_open else -(sessions + 1)
    n = 0
    for symbol, bars in bars_by_symbol.items():
        if len(bars) < abs(idx):
            continue
        bar = bars[idx]
        as_of = cal._utc_naive(bar.date, cal.CLOSE)
        b = db.scalar(select(Baseline).where(Baseline.user_id == user_id, Baseline.symbol == symbol))
        if b is None:
            b = Baseline(user_id=user_id, symbol=symbol, committed_price=bar.close, committed_as_of=as_of, committed_seen_at=as_of)
            db.add(b)
        else:
            b.committed_price, b.committed_as_of, b.committed_seen_at = bar.close, as_of, as_of
            b.pending_price = b.pending_as_of = b.pending_seen_at = None
        n += 1
    return n
