"""Assemble a briefing for one watchlist: quotes + history + the user's
baseline and levels → scored, tiered, explained items."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas
from ..market import calendar as cal
from ..market.store import get_bars_many, get_news_many, get_quotes
from ..models import PriceLevel, Quote, SymbolMeta, User, Watchlist
from . import baselines as bl
from .significance import Bar, BaselineIn, LevelIn, QuoteIn, assess, humanize_since

TIER_ORDER = {"attention": 0, "notable": 1, "quiet": 2}


def freshness(q: Quote | None, now: datetime, state: cal.MarketState) -> schemas.Freshness:
    if q is None:
        return schemas.Freshness(status="missing", label="No data yet", as_of=None, fetched_at=None, source=None)
    print_age = now - q.as_of
    if state.is_open:
        if print_age <= timedelta(minutes=2):
            status, label = "live", "Live"
        elif print_age <= timedelta(minutes=20):
            status, label = "delayed", f"Delayed ~{max(1, int(print_age.total_seconds() // 60))} min"
        else:
            status, label = "stale", f"Stale — last print {humanize_since(q.as_of, now)}"
    else:
        if q.as_of >= state.last_close - timedelta(minutes=30):
            status, label = "closed", f"At close, {cal._ist(q.as_of):%a %d %b}"
        else:
            status, label = "stale", f"Last print {cal._ist(q.as_of):%d %b %H:%M} IST"
    return schemas.Freshness(status=status, label=label, as_of=q.as_of, fetched_at=q.fetched_at, source=q.source)


def apply_news(tier: str, reasons: list, new_news: list[schemas.NewsOut]):
    """News is context, not a signal on its own — except when there is a lot
    of it. A single headline attaches to an existing move as the likely
    'why'; three or more new headlines on a quiet stock is itself notable."""
    from .significance import Reason

    if not new_news:
        return tier, reasons
    top = new_news[0]
    n = len(new_news)
    if tier in ("attention", "notable"):
        text = f"In the news: “{top.title}” ({top.source})" + (f" +{n - 1} more" if n > 1 else "")
        reasons = reasons + [Reason("news", "medium", text)]
    elif n >= 3:
        tier = "notable"
        reasons = reasons + [Reason("news", "medium", f"Unusual news flow: {n} new headlines since you looked")]
    else:
        reasons = reasons + [Reason("news", "low", f"{n} new headline{'s' if n > 1 else ''} since you looked")]
    return tier, reasons


def headline(attention: int, notable: int, quiet: int, missing: int, new_visit: bool, any_change: bool) -> str:
    total = attention + notable + quiet
    if total == 0:
        return "Your watchlist is empty — add a few symbols to get started."
    if not any_change:
        standing = attention + notable
        if standing:
            return f"No new prices since you last looked — {standing} still stand{'s' if standing == 1 else ''} out."
        return "Nothing has changed since you last looked."
    if attention == 0 and notable == 0:
        return f"All quiet. {quiet} stock{'s' if quiet != 1 else ''} moved within their normal range."
    parts = []
    if attention:
        parts.append(f"{attention} need{'s' if attention == 1 else ''} your attention")
    if notable:
        parts.append(f"{notable} worth a glance")
    if quiet:
        parts.append(f"{quiet} quiet")
    return ", ".join(parts) + "."


def build_briefing(
    db: Session,
    user: User,
    wl: Watchlist,
    *,
    visit_id: str | None,
    now: datetime,
    idle_minutes: int,
    data_status: dict,
) -> schemas.BriefingOut:
    state = cal.market_state(now)
    new_visit = bl.touch_visit(db, user, visit_id, now, idle_minutes)

    symbols = [it.symbol for it in wl.items]
    quotes = get_quotes(db, symbols)
    bars_by = get_bars_many(db, symbols, limit=260)
    metas = {m.symbol: m for m in db.scalars(select(SymbolMeta).where(SymbolMeta.symbol.in_(symbols)))} if symbols else {}
    levels_by: dict[str, list[PriceLevel]] = {s: [] for s in symbols}
    if symbols:
        for lv in db.scalars(select(PriceLevel).where(PriceLevel.user_id == user.id, PriceLevel.symbol.in_(symbols))):
            levels_by[lv.symbol].append(lv)
    baselines = bl.get_baselines(db, user.id, symbols)
    frac = cal.session_fraction_elapsed(now)
    news_by = get_news_many(db, symbols, since=now - timedelta(days=7))

    items: list[schemas.BriefingItem] = []
    counts = {"attention": 0, "notable": 0, "quiet": 0}
    missing = 0
    any_change = False

    for it in wl.items:
        meta = metas.get(it.symbol)
        name = meta.name if meta else it.symbol
        sector = meta.sector if meta else None
        q = quotes.get(it.symbol)
        bars = [Bar(b.date, b.close, b.high, b.low, b.volume) for b in bars_by.get(it.symbol, [])]
        spark = [b.close for b in bars[-30:]]
        lv_out = [schemas.LevelOut(id=l.id, symbol=l.symbol, price=l.price, direction=l.direction, note=l.note,
                                   created_at=l.created_at) for l in levels_by[it.symbol]]

        if q is None:
            missing += 1
            items.append(schemas.BriefingItem(
                symbol=it.symbol, name=name, sector=sector, tier="quiet", score=0, quote=None, since=None,
                reasons=[schemas.ReasonOut(kind="info", severity="low", text="Waiting for first quote…")],
                volume_ratio=None, range_position_52w=None, high_52w=None, low_52w=None, sigma_daily=None,
                streak=0, sparkline=spark, levels=lv_out, levels_crossed=[],
                news=schemas.NewsSummary(new_count=0, items=[])))
            continue

        base = bl.record_seen(db, user.id, it.symbol, q, now, baselines.get(it.symbol))
        b_in = BaselineIn(price=base.committed_price, as_of=base.committed_as_of, seen_at=base.committed_seen_at)
        a = assess(
            bars, QuoteIn(q.price, q.as_of, q.prev_close, q.open, q.volume), b_in,
            [LevelIn(l.id, l.price, l.direction, l.note) for l in levels_by[it.symbol]],
            now, market_open=state.is_open, session_fraction=frac,
        )
        if q.as_of > b_in.as_of:
            any_change = True

        # ---- news: what was published after they last looked ------------
        news_items = news_by.get(it.symbol, [])
        news_out = [schemas.NewsOut(title=n.title, url=n.url, source=n.source, published_at=n.published_at,
                                    is_new=n.published_at > b_in.seen_at) for n in news_items[:6]]
        new_news = [n for n in news_out if n.is_new]
        tier, reasons = apply_news(a.tier, a.reasons, new_news)
        if tier != a.tier:
            a.tier = tier
        a.reasons = reasons
        if new_news:
            a.score += min(1.0, 0.25 * len(new_news))
        counts[a.tier] += 1
        items.append(schemas.BriefingItem(
            symbol=it.symbol, name=name, sector=sector, tier=a.tier, score=a.score,
            quote=schemas.QuoteOut(price=q.price, prev_close=q.prev_close, open=q.open, day_high=q.day_high,
                                   day_low=q.day_low, volume=q.volume, day_change_pct=a.day_change_pct,
                                   freshness=freshness(q, now, state)),
            since=schemas.SinceOut(baseline_price=b_in.price, baseline_as_of=b_in.as_of, seen_at=b_in.seen_at,
                                   seen_label=humanize_since(b_in.seen_at, now), change_abs=a.change_abs,
                                   change_pct=a.change_pct, sessions=a.sessions, z=a.z),
            reasons=[schemas.ReasonOut(kind=r.kind, severity=r.severity, text=r.text) for r in a.reasons],
            volume_ratio=a.volume_ratio, range_position_52w=a.range_position_52w, high_52w=a.high_52w,
            low_52w=a.low_52w, sigma_daily=a.sigma_daily, streak=a.streak, sparkline=spark, levels=lv_out,
            levels_crossed=a.levels_crossed,
            news=schemas.NewsSummary(new_count=len(new_news), items=news_out),
        ))

    # Attention first, then by score; quiet ones keep the user's own order.
    items.sort(key=lambda i: (TIER_ORDER[i.tier], -i.score if i.tier != "quiet" else 0))

    note = None
    if data_status.get("degraded"):
        note = f"Primary feed unavailable — showing {data_status.get('active')} data."
    return schemas.BriefingOut(
        watchlist_id=wl.id,
        watchlist_version=wl.version,
        generated_at=now,
        new_visit=new_visit,
        market=schemas.MarketOut(is_open=state.is_open, phase=state.phase, session_date=state.session_date.isoformat(),
                                 last_close=state.last_close, next_open=state.next_open),
        data=schemas.DataStatus(active_provider=data_status.get("active", "unknown"),
                                degraded=bool(data_status.get("degraded")), note=note),
        summary=schemas.BriefingSummary(**counts, missing=missing,
                                        headline=headline(counts["attention"], counts["notable"], counts["quiet"],
                                                          missing, new_visit, any_change)),
        items=items,
    )
