"""Analyst memory: the thesis you wrote, and whether it still holds.

The rest of Since answers *"what changed since you last looked?"*. That is a
question about attention. This module answers the question one level up —
*"is the reason you were interested still true?"* — which is a question about
conviction, and it is the one people actually get wrong. Everybody remembers
the price they bought at. Almost nobody remembers **why**, and so nobody can
tell the difference between "my thesis broke" and "the price fell".

The mechanism is deliberately the same shape as the briefing, one clock up:

    briefing:  baseline = the price you last SAW      → trigger = a new visit
    thesis:    anchor   = the price you last THOUGHT  → trigger = a material
                          about this stock              change, or the horizon

An *anchor* is the price at the moment the thesis was written, and it moves
forward every time you review it — so "since you last thought about this"
stays literally true, and re-reviewing does not immediately re-fire.

Nothing here invents a judgement. The app never says whether your thesis is
right; it says *something happened that is worth re-reading it against*, shows
you what you wrote and what the price has done since, and records your answer.
The verdict is always the user's.

Pure functions over plain data, like `significance` — the DB layer is at the
bottom of the file and does no reasoning.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..market import calendar as cal
from ..models import NewsItem, Quote, SymbolMeta, Thesis, ThesisReview
from .significance import Bar, fmt_pct, humanize_since, sigma_daily

# Two different reasons a move should make you re-read your reason, needing two
# different tests.
#
#   RARE — statistically surprising for this stock. The same z-machinery the
#   briefing uses: 2σ over the whole window since the anchor.
#
#   MATERIAL — big in plain terms, even where a random walk would shrug. This
#   one is not optional. Because z divides by √n, a stock that bleeds 26% over
#   a quarter scores about 1.2σ and would never prompt — and "down a quarter of
#   its value since you wrote this" is exactly when you most need to re-read
#   why you were interested. Volatility-normalising is right for *attention*,
#   which is the briefing's job minute to minute; it is wrong for *conviction*,
#   where what matters is the size of the outcome, not its surprise.
#
# The z floor on MATERIAL is deliberately weak (0.5σ, not 1σ). It exists only
# to exclude the pathological case — a stock for which 20% is a quiet
# fortnight — not to re-impose the rarity test through the back door. The
# asymmetry is intentional: a prompt you dismiss costs one click, a thesis you
# never re-read costs the whole feature.
MOVE_Z = 2.0
MATERIAL_PCT = 0.20
MATERIAL_Z = 0.5
NEWS_BURST = 6          # headlines since the anchor that suggest the story moved
DEFAULT_HORIZON = 90    # days: re-read it eventually even if nothing happened
VERDICTS = ("holds", "weakened", "broken")


@dataclass
class ThesisView:
    id: int
    symbol: str
    name: str
    text: str
    status: str
    created_at: datetime
    anchored_at: datetime
    age_label: str              # "written 3 weeks ago"
    anchor_price: float | None
    price: float | None
    change_pct: float | None    # since the anchor
    sessions: int
    z: float | None
    review_due: bool
    trigger: str | None         # move | range | news | time
    trigger_text: str | None    # why we are asking, in one sentence
    review_count: int
    last_verdict: str | None
    last_reviewed_at: datetime | None
    horizon_days: int


def _age_label(then: datetime, now: datetime) -> str:
    days = (cal._ist(now).date() - cal._ist(then).date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        return f"{days // 7} weeks ago"
    if days < 365:
        return f"{max(1, days // 30)} months ago"
    return f"{days // 365}y ago"


def evaluate(
    *,
    thesis_id: int,
    symbol: str,
    name: str,
    text: str,
    status: str,
    created_at: datetime,
    anchored_at: datetime,
    anchor_price: float | None,
    anchor_as_of: datetime | None,
    horizon_days: int,
    snoozed_until: datetime | None,
    quote_price: float | None,
    quote_as_of: datetime | None,
    bars: list[Bar],
    high_52w: float | None,
    low_52w: float | None,
    news_since_anchor: int,
    review_count: int,
    last_verdict: str | None,
    last_reviewed_at: datetime | None,
    now: datetime,
) -> ThesisView:
    """Decide whether this thesis deserves a prompt, and say why in words.

    Order matters: a 52-week breach beats a big move beats a news burst beats
    the calendar, because that is the order in which they are informative. We
    surface at most one reason — a prompt that lists four reasons reads like
    an alert, and alerts get dismissed.
    """
    sig, _ = sigma_daily(bars)
    change_pct: float | None = None
    z: float | None = None
    sessions = 0

    if anchor_price and quote_price and anchor_price > 0 and quote_price > 0:
        change_pct = quote_price / anchor_price - 1
        if anchor_as_of and quote_as_of:
            sessions = cal.sessions_between(anchor_as_of, quote_as_of)
        if abs(change_pct) > 1e-9:
            z = math.log(quote_price / anchor_price) / (sig * math.sqrt(max(sessions, 1)))

    trigger: str | None = None
    trigger_text: str | None = None

    if status == "open" and quote_price is not None:
        moved = change_pct is not None and abs(change_pct) >= 0.02
        if high_52w is not None and quote_price >= high_52w and moved:
            trigger, trigger_text = "range", "It is at a 52-week high — the setup you described is not the setup you own now."
        elif low_52w is not None and quote_price <= low_52w and moved:
            trigger, trigger_text = "range", "It is at a 52-week low — worth checking whether the story broke or only the price."
        elif z is not None and (abs(z) >= MOVE_Z
                                or (abs(change_pct or 0) >= MATERIAL_PCT and abs(z) >= MATERIAL_Z)):
            direction = "up" if change_pct and change_pct > 0 else "down"
            span = "since you wrote this" if review_count == 0 else "since you last reviewed this"
            rare = abs(z) >= MOVE_Z
            trigger = "move"
            trigger_text = (
                f"{direction.capitalize()} {fmt_pct(change_pct or 0, signed=False)} {span} — "
                + (f"a {abs(z):.1f}σ move, well outside what this stock normally does. "
                   if rare else
                   f"not a wild move by this stock's standards ({abs(z):.1f}σ), but "
                   f"{fmt_pct(change_pct or 0, signed=False)} {direction} on where you wrote it is a different "
                   "position than the one you described. ")
                + "Prices move for reasons; check whether yours changed."
            )
        elif news_since_anchor >= NEWS_BURST:
            trigger = "news"
            trigger_text = (f"{news_since_anchor} headlines since you wrote this. That much coverage usually means "
                            "the story moved, in one direction or the other.")
        elif (now - anchored_at) >= timedelta(days=horizon_days):
            trigger = "time"
            trigger_text = (f"You set a {horizon_days}-day horizon and it has passed. Nothing dramatic happened — "
                            "which is itself worth knowing.")

    # A dismissal ("remind me later") silences the current reason, not future
    # stronger ones: a 52-week breach still interrupts a snooze.
    if trigger and snoozed_until and now < snoozed_until and trigger != "range":
        trigger, trigger_text = None, None

    return ThesisView(
        id=thesis_id, symbol=symbol, name=name, text=text, status=status,
        created_at=created_at, anchored_at=anchored_at,
        age_label=_age_label(created_at, now),
        anchor_price=anchor_price, price=quote_price, change_pct=change_pct,
        sessions=sessions, z=round(z, 2) if z is not None else None,
        review_due=trigger is not None, trigger=trigger, trigger_text=trigger_text,
        review_count=review_count, last_verdict=last_verdict, last_reviewed_at=last_reviewed_at,
        horizon_days=horizon_days,
    )


# ------------------------------------------------------------------- db layer


def open_thesis(db: Session, user_id: int, symbol: str) -> Thesis | None:
    return db.scalar(
        select(Thesis).where(Thesis.user_id == user_id, Thesis.symbol == symbol, Thesis.status == "open")
    )


def load_views(db: Session, user_id: int, now: datetime, *, symbols: list[str] | None = None,
               include_closed: bool = False) -> list[ThesisView]:
    """Evaluate every thesis (optionally restricted to some symbols) in a
    handful of queries rather than one per row — the briefing calls this on
    every request."""
    stmt = select(Thesis).where(Thesis.user_id == user_id).options(selectinload(Thesis.reviews))
    if not include_closed:
        stmt = stmt.where(Thesis.status == "open")
    if symbols is not None:
        if not symbols:
            return []
        stmt = stmt.where(Thesis.symbol.in_(symbols))
    rows = list(db.scalars(stmt.order_by(Thesis.created_at.desc())))
    if not rows:
        return []

    syms = sorted({t.symbol for t in rows})
    quotes = {q.symbol: q for q in db.scalars(select(Quote).where(Quote.symbol.in_(syms)))}
    metas = {m.symbol: m for m in db.scalars(select(SymbolMeta).where(SymbolMeta.symbol.in_(syms)))}

    from ..market.store import get_bars_many
    bars_by = get_bars_many(db, syms, limit=260)

    # One grouped count for the news bursts, instead of a query per thesis.
    oldest = min(t.anchored_at for t in rows)
    counts: dict[tuple[str, int], int] = {}
    news_rows = db.execute(
        select(NewsItem.symbol, NewsItem.published_at)
        .where(NewsItem.symbol.in_(syms), NewsItem.published_at >= oldest)
    ).all()
    for t in rows:
        counts[(t.symbol, t.id)] = sum(1 for s, p in news_rows if s == t.symbol and p >= t.anchored_at)

    out: list[ThesisView] = []
    for t in rows:
        q = quotes.get(t.symbol)
        raw = bars_by.get(t.symbol, [])
        bars = [Bar(b.date, b.close, b.high, b.low, b.volume) for b in raw]
        window = bars[-250:]
        high = max((b.high for b in window), default=None) if len(window) >= 20 else None
        low = min((b.low for b in window), default=None) if len(window) >= 20 else None
        last = t.reviews[0] if t.reviews else None
        out.append(evaluate(
            thesis_id=t.id, symbol=t.symbol,
            name=metas[t.symbol].name if t.symbol in metas else t.symbol,
            text=t.text, status=t.status, created_at=t.created_at, anchored_at=t.anchored_at,
            anchor_price=t.anchor_price, anchor_as_of=t.anchor_as_of, horizon_days=t.horizon_days,
            snoozed_until=t.snoozed_until,
            quote_price=q.price if q else None, quote_as_of=q.as_of if q else None,
            bars=bars, high_52w=high, low_52w=low,
            news_since_anchor=counts.get((t.symbol, t.id), 0),
            review_count=len(t.reviews), last_verdict=last.verdict if last else None,
            last_reviewed_at=last.created_at if last else None,
            now=now,
        ))
    return out


def record_review(db: Session, t: Thesis, *, verdict: str, note: str | None, view: ThesisView,
                  now: datetime, quote: Quote | None) -> ThesisReview:
    """Store the answer, then move the anchor forward so the same trigger does
    not fire again the next second. A 'broken' verdict closes the thesis: the
    honest end state is a closed position or a rewritten reason, not a thesis
    you keep re-answering 'no' to."""
    r = ThesisReview(
        thesis_id=t.id, verdict=verdict, note=(note or "").strip() or None,
        trigger=view.trigger or "manual", trigger_text=view.trigger_text,
        price_at_review=quote.price if quote else None,
        change_pct=view.change_pct, sessions=view.sessions, created_at=now,
    )
    db.add(r)
    if quote is not None:
        t.anchor_price = quote.price
        t.anchor_as_of = quote.as_of
    t.anchored_at = now
    t.snoozed_until = None
    if verdict == "broken":
        t.status, t.closed_at = "closed", now
    return r


def history(db: Session, user_id: int) -> dict:
    """The scoreboard: how often your reasons survived contact with the market.

    This is the number nobody keeps on themselves, and it is the whole point of
    writing the thesis down in the first place.
    """
    rows = db.execute(
        select(ThesisReview.verdict, func.count())
        .join(Thesis, Thesis.id == ThesisReview.thesis_id)
        .where(Thesis.user_id == user_id)
        .group_by(ThesisReview.verdict)
    ).all()
    by = {v: n for v, n in rows}
    total = sum(by.values())
    return {
        "reviews": total,
        "holds": by.get("holds", 0),
        "weakened": by.get("weakened", 0),
        "broken": by.get("broken", 0),
        "hold_rate": (by.get("holds", 0) / total) if total else None,
    }


def label_since(view: ThesisView, now: datetime) -> str:
    return humanize_since(view.anchored_at, now)


def to_out(v: ThesisView, reviews: list[ThesisReview] | None = None):
    from .. import schemas

    return schemas.ThesisOut(
        id=v.id, symbol=v.symbol, name=v.name, text=v.text, status=v.status,
        created_at=v.created_at, anchored_at=v.anchored_at, age_label=v.age_label,
        anchor_price=v.anchor_price, price=v.price, change_pct=v.change_pct,
        sessions=v.sessions, z=v.z, review_due=v.review_due, trigger=v.trigger,
        trigger_text=v.trigger_text, review_count=v.review_count,
        last_verdict=v.last_verdict, last_reviewed_at=v.last_reviewed_at,
        horizon_days=v.horizon_days,
        reviews=[
            schemas.ReviewOut(id=r.id, verdict=r.verdict, note=r.note, trigger=r.trigger,
                              trigger_text=r.trigger_text, price_at_review=r.price_at_review,
                              change_pct=r.change_pct, sessions=r.sessions, created_at=r.created_at)
            for r in (reviews or [])
        ],
    )
