"""Assemble a briefing for one watchlist: quotes + history + the user's
baseline and levels → scored, tiered, explained items."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas
from ..market import calendar as cal
from ..market.store import close_on_or_before, get_bars, get_bars_many, get_fundamentals, get_news_many, get_quotes
from ..models import Pin, PriceLevel, Quote, SymbolMeta, User, Watchlist, WatchlistItem
from . import baselines as bl
from . import thesis as th
from .significance import Bar, BaselineIn, LevelIn, QuoteIn, assess, describe_unusual, humanize_since

TIER_ORDER = {"attention": 0, "notable": 1, "quiet": 2}
MARKET_INDEX = "^NSEI"


def freshness(q: Quote | None, now: datetime, state: cal.MarketState) -> schemas.Freshness:
    if q is None:
        return schemas.Freshness(status="missing", label="No data yet", as_of=None, fetched_at=None, source=None)
    print_age = now - q.as_of
    declared = q.delay_minutes   # vendor's own statement of lag; trumps our clock arithmetic
    if state.is_open:
        if print_age > timedelta(minutes=20 + (declared or 0)):
            status, label = "stale", f"Stale — last print {humanize_since(q.as_of, now)}"
        elif declared:
            status, label = "delayed", f"Delayed {declared} min (feed)"
        elif print_age <= timedelta(minutes=2):
            status, label = "live", "Live"
        else:
            status, label = "delayed", f"Delayed ~{max(1, int(print_age.total_seconds() // 60))} min"
    else:
        if q.as_of >= state.last_close - timedelta(minutes=30):
            status, label = "closed", f"At close, {cal._ist(q.as_of):%a %d %b}"
        else:
            status, label = "stale", f"Last print {cal._ist(q.as_of):%d %b %H:%M} IST"
    return schemas.Freshness(status=status, label=label, as_of=q.as_of, fetched_at=q.fetched_at, source=q.source,
                             delay_minutes=q.delay_minutes)


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
    items, counts, missing, any_change, first_visit = assess_symbols(db, user, symbols, now, state)

    # Analyst memory: your own reasons, and whether anything happened that is
    # worth re-reading them against.
    views = {v.symbol: v for v in th.load_views(db, user.id, now, symbols=symbols)}
    for it in items:
        v = views.get(it.symbol)
        if v is not None:
            it.thesis = th.to_out(v)
    due = sum(1 for v in views.values() if v.review_due)

    # Only holdings that actually have something new to compare contribute to
    # the net. Averaging in a pile of "no new print" zeros would drag the
    # number toward nought and make a closed market look like a flat one.
    moves = [i.since.change_pct for i in items if i.since is not None and not i.since.same_print]
    net = sum(moves) / len(moves) if moves else None

    note = None
    if data_status.get("degraded"):
        note = f"Primary feed unavailable — showing {data_status.get('active')} data."
    return schemas.BriefingOut(
        indices=index_strip(db, now, state),
        watchlist_id=wl.id,
        watchlist_version=wl.version,
        generated_at=now,
        new_visit=new_visit,
        first_visit=first_visit,
        market=schemas.MarketOut(is_open=state.is_open, phase=state.phase, session_date=state.session_date.isoformat(),
                                 last_close=state.last_close, next_open=state.next_open),
        data=schemas.DataStatus(active_provider=data_status.get("active", "unknown"),
                                degraded=bool(data_status.get("degraded")), note=note),
        summary=schemas.BriefingSummary(**counts, missing=missing,
                                        theses_due=due, theses_open=len(views), net_change_pct=net,
                                        headline=headline(counts["attention"], counts["notable"], counts["quiet"],
                                                          missing, new_visit, any_change)),
        items=items,
    )


def index_strip(db: Session, now: datetime, state: cal.MarketState) -> list[schemas.IndexOut]:
    """The two index tiles at the top of the command strip. Cheap: they are
    already tracked for the market-relative scoring, so this is two lookups."""
    from .analytics import INDICES, _closes, _ret

    out: list[schemas.IndexOut] = []
    for sym in INDICES:
        meta = db.get(SymbolMeta, sym)
        q = db.get(Quote, sym)
        bars = get_bars(db, sym, limit=40)
        if q is None and not bars:
            continue
        pts = _closes(bars, q, state.is_open)
        out.append(schemas.IndexOut(
            symbol=sym, name=meta.name if meta else sym,
            price=pts[-1][1] if pts else None,
            ret_1d=_ret(pts, 1), ret_5d=_ret(pts, 5), ret_20d=_ret(pts, 20),
            sparkline=[p for _, p in pts[-30:]],
        ))
    return out


def build_board(db: Session, user: User, now: datetime) -> schemas.BoardOut:
    """The pinned strip: the user's always-watch symbols across every list,
    scored exactly like the briefing. Looking at the tile counts as seeing."""
    state = cal.market_state(now)
    pins = db.scalars(select(Pin).where(Pin.user_id == user.id).order_by(Pin.position, Pin.id)).all()
    items, *_ = assess_symbols(db, user, [p.symbol for p in pins], now, state, keep_order=True)
    return schemas.BoardOut(generated_at=now, items=items)


def assess_symbols(db: Session, user: User, symbols: list[str], now: datetime, state: cal.MarketState,
                   *, keep_order: bool = False):
    pinned = set(db.scalars(select(Pin.symbol).where(Pin.user_id == user.id)))
    # Which watchlist a symbol lives in (first match) — lets a pinned tile jump to its card.
    home: dict[str, int] = {}
    if symbols:
        for wid, sym in db.execute(
            select(WatchlistItem.watchlist_id, WatchlistItem.symbol)
            .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
            .where(Watchlist.user_id == user.id, WatchlistItem.symbol.in_(symbols))
            .order_by(WatchlistItem.watchlist_id)
        ):
            home.setdefault(sym, wid)
    quotes = get_quotes(db, symbols)
    bars_by = get_bars_many(db, symbols, limit=260)
    metas = {m.symbol: m for m in db.scalars(select(SymbolMeta).where(SymbolMeta.symbol.in_(symbols)))} if symbols else {}
    levels_by: dict[str, list[PriceLevel]] = {s: [] for s in symbols}
    if symbols:
        for lv in db.scalars(select(PriceLevel).where(PriceLevel.user_id == user.id, PriceLevel.symbol.in_(symbols))):
            levels_by[lv.symbol].append(lv)
    baselines = bl.get_baselines(db, user.id, symbols)
    first_visit = bool(symbols) and not baselines
    frac = cal.session_fraction_elapsed(now)
    news_by = get_news_many(db, symbols, since=now - timedelta(days=7))
    funda_by = get_fundamentals(db, symbols)
    # The market itself, for "how much of this move is just Nifty?"
    index_q = db.get(Quote, MARKET_INDEX)
    index_bars = get_bars(db, MARKET_INDEX, limit=80) if index_q else []

    def market_change(baseline_as_of: datetime) -> float | None:
        if index_q is None or not index_bars:
            return None
        ref = close_on_or_before(index_bars, cal._ist(baseline_as_of).date())
        if ref is None or ref.close <= 0 or index_q.as_of <= baseline_as_of:
            return None
        return index_q.price / ref.close - 1

    items: list[schemas.BriefingItem] = []
    counts = {"attention": 0, "notable": 0, "quiet": 0}
    missing = 0
    any_change = False

    for sym in symbols:
        meta = metas.get(sym)
        name = meta.name if meta else sym
        sector = meta.sector if meta else None
        q = quotes.get(sym)
        bars = [Bar(b.date, b.close, b.high, b.low, b.volume) for b in bars_by.get(sym, [])]
        spark = [b.close for b in bars[-30:]]
        lv_out = [schemas.LevelOut(id=l.id, symbol=l.symbol, price=l.price, direction=l.direction, note=l.note,
                                   created_at=l.created_at) for l in levels_by[sym]]
        f = funda_by.get(sym)
        funda_out = None
        if f is not None and f.source != "none":
            funda_out = schemas.FundamentalsOut(
                source=f.source, fetched_at=f.fetched_at, as_of=f.as_of, market_cap=f.market_cap,
                pe_trailing=f.pe_trailing, pe_forward=f.pe_forward, price_to_book=f.price_to_book,
                eps_trailing=f.eps_trailing, book_value=f.book_value, roe=f.roe,
                dividend_yield=f.dividend_yield, debt_to_equity=f.debt_to_equity,
                profit_margin=f.profit_margin, revenue_growth=f.revenue_growth, beta=f.beta)
        common = dict(symbol=sym, name=name, sector=sector, pinned=sym in pinned, watchlist_id=home.get(sym),
                      fundamentals=funda_out)

        if q is None:
            missing += 1
            if meta is not None and meta.unavailable:
                why = schemas.ReasonOut(kind="error", severity="high",
                                        text=f"Not available on the {meta.unavailable_reason.split()[-1] if meta.unavailable_reason else 'data'} feed — "
                                             "the ticker may be renamed or delisted. Remove it or add the new symbol.")
            else:
                why = schemas.ReasonOut(kind="info", severity="low", text="Waiting for first quote…")
            items.append(schemas.BriefingItem(
                **common, tier="quiet", score=0, quote=None, since=None,
                reasons=[why],
                volume_ratio=None, range_position_52w=None, high_52w=None, low_52w=None, sigma_daily=None,
                streak=0, sparkline=spark, levels=lv_out, levels_crossed=[],
                news=schemas.NewsSummary(new_count=0, items=[])))
            continue

        base = bl.record_seen(db, user.id, sym, q, now, baselines.get(sym))
        b_in = BaselineIn(price=base.committed_price, as_of=base.committed_as_of, seen_at=base.committed_seen_at)
        a = assess(
            bars, QuoteIn(q.price, q.as_of, q.prev_close, q.open, q.volume), b_in,
            [LevelIn(l.id, l.price, l.direction, l.note) for l in levels_by[sym]],
            now, market_open=state.is_open, session_fraction=frac,
            market_change_pct=market_change(b_in.as_of) if sym != MARKET_INDEX else None,
        )
        u_label, u_text, u_window = describe_unusual(a.z, a.change_pct, a.sigma_daily, a.sessions, state.is_open, frac)
        if q.as_of > b_in.as_of:
            any_change = True

        # ---- news: what was published after they last looked ------------
        news_items = news_by.get(sym, [])
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
            **common, tier=a.tier, score=a.score,
            quote=schemas.QuoteOut(price=q.price, prev_close=q.prev_close, open=q.open, day_high=q.day_high,
                                   day_low=q.day_low, volume=q.volume, day_change_pct=a.day_change_pct,
                                   freshness=freshness(q, now, state)),
            since=schemas.SinceOut(baseline_price=b_in.price, baseline_as_of=b_in.as_of, seen_at=b_in.seen_at,
                                   seen_label=humanize_since(b_in.seen_at, now), change_abs=a.change_abs,
                                   change_pct=a.change_pct, sessions=a.sessions, z=a.z, same_print=a.same_print,
                                   unusual=schemas.UnusualOut(label=u_label, text=u_text, z=a.z, typical_move_pct=a.sigma_daily,
                                                              typical_window_pct=u_window),
                                   market_change_pct=a.market_change_pct, market_share=a.market_share),
            reasons=[schemas.ReasonOut(kind=r.kind, severity=r.severity, text=r.text) for r in a.reasons],
            volume_ratio=a.volume_ratio, range_position_52w=a.range_position_52w, high_52w=a.high_52w,
            low_52w=a.low_52w, sigma_daily=a.sigma_daily, streak=a.streak, sparkline=spark, levels=lv_out,
            levels_crossed=a.levels_crossed,
            news=schemas.NewsSummary(new_count=len(new_news), items=news_out),
        ))

    # Attention first, then by score; quiet ones keep the user's own order.
    if not keep_order:
        items.sort(key=lambda i: (TIER_ORDER[i.tier], -i.score if i.tier != "quiet" else 0))
    return items, counts, missing, any_change, first_visit
