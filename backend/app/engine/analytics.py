"""Analytics over the bars we already store: the Market page (what's moving),
the Compare page (rebased performance, volatility, correlation) and the News
feed. No new data sources, no predictions, no recommendations.

Why no "opportunities": telling people what to buy is investment advice, a
regulated activity (SEBI). Showing what *happened* — sector moves, unusual
moves, fresh 52-week highs — is information. The page says so.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas
from ..market import calendar as cal
from ..market.store import get_bars_many, get_quotes
from ..market.universe import BY_SYMBOL, UNIVERSE
from ..models import Baseline, DailyBar, NewsItem, Pin, Quote, SymbolMeta, WatchlistItem, Watchlist
from .significance import Bar, sigma_daily

INDICES = ["^NSEI", "^NSEBANK"]


# ------------------------------------------------------------------ helpers


def _closes(bars: list[DailyBar], q: Quote | None, market_open: bool) -> list[tuple[date, float]]:
    """Completed closes plus today's live print as the last point while open."""
    pts = [(b.date, b.close) for b in bars]
    if q is not None and market_open and (not pts or cal._ist(q.as_of).date() > pts[-1][0]):
        pts.append((cal._ist(q.as_of).date(), q.price))
    elif q is not None and pts and cal._ist(q.as_of).date() > pts[-1][0]:
        pts.append((cal._ist(q.as_of).date(), q.price))
    return pts


def _ret(pts: list[tuple[date, float]], sessions: int) -> float | None:
    if len(pts) <= sessions or pts[-1 - sessions][1] <= 0:
        return None
    return pts[-1][1] / pts[-1 - sessions][1] - 1


def _z(pts: list[tuple[date, float]], sessions: int, sig: float) -> float | None:
    r = _ret(pts, sessions)
    if r is None:
        return None
    return math.log(1 + r) / (sig * math.sqrt(max(sessions, 1)))


# ------------------------------------------------------------------- market


def build_market(db: Session, now: datetime) -> schemas.MarketPageOut:
    state = cal.market_state(now)
    symbols = [s.symbol for s in UNIVERSE]
    bars_by = get_bars_many(db, symbols, limit=260)
    quotes = get_quotes(db, symbols)
    scanned = [s for s in symbols if len(bars_by.get(s, [])) >= 25]

    def snap(sym: str) -> dict:
        info = BY_SYMBOL[sym]
        bars = bars_by.get(sym, [])
        q = quotes.get(sym)
        pts = _closes(bars, q, state.is_open)
        sig, _ = sigma_daily([Bar(b.date, b.close, b.high, b.low, b.volume) for b in bars])
        hi = max((b.high for b in bars[-250:]), default=None)
        lo = min((b.low for b in bars[-250:]), default=None)
        price = pts[-1][1] if pts else None
        return dict(symbol=sym, name=info.name, sector=info.sector, price=price,
                    ret_1d=_ret(pts, 1), ret_5d=_ret(pts, 5), ret_20d=_ret(pts, 20),
                    z_5d=_z(pts, 5, sig), sigma_daily=sig, high_52w=hi, low_52w=lo,
                    at_high=bool(price and hi and price >= hi * 0.995), at_low=bool(price and lo and price <= lo * 1.005),
                    sparkline=[p for _, p in pts[-30:]])

    snaps = {s: snap(s) for s in scanned}
    stocks = [v for k, v in snaps.items() if k not in INDICES]

    indices = [schemas.IndexOut(symbol=s, name=BY_SYMBOL[s].name, price=snaps[s]["price"], ret_1d=snaps[s]["ret_1d"],
                                ret_5d=snaps[s]["ret_5d"], ret_20d=snaps[s]["ret_20d"], sparkline=snaps[s]["sparkline"])
               for s in INDICES if s in snaps]

    # Sector aggregates: equal-weighted mean of members we have data for.
    by_sector: dict[str, list[dict]] = {}
    for v in stocks:
        by_sector.setdefault(v["sector"], []).append(v)
    sectors = []
    for sec, members in by_sector.items():
        def mean(key):
            xs = [m[key] for m in members if m[key] is not None]
            return sum(xs) / len(xs) if xs else None
        sectors.append(schemas.SectorOut(sector=sec, n=len(members), ret_1d=mean("ret_1d"), ret_5d=mean("ret_5d"),
                                         ret_20d=mean("ret_20d"), members=[m["symbol"] for m in members]))
    sectors.sort(key=lambda s: -(s.ret_5d or 0))

    def mover(v: dict) -> schemas.MoverOut:
        return schemas.MoverOut(symbol=v["symbol"], name=v["name"], sector=v["sector"], price=v["price"],
                                ret_1d=v["ret_1d"], ret_5d=v["ret_5d"], ret_20d=v["ret_20d"], z_5d=v["z_5d"],
                                sparkline=v["sparkline"])

    with_5d = [v for v in stocks if v["ret_5d"] is not None]
    gainers = [mover(v) for v in sorted(with_5d, key=lambda v: -v["ret_5d"])[:6]]
    losers = [mover(v) for v in sorted(with_5d, key=lambda v: v["ret_5d"])[:6]]
    unusual = [mover(v) for v in sorted((v for v in stocks if v["z_5d"] is not None), key=lambda v: -abs(v["z_5d"]))[:6]]
    highs = [mover(v) for v in stocks if v["at_high"]]
    lows = [mover(v) for v in stocks if v["at_low"]]

    return schemas.MarketPageOut(
        generated_at=now, session_date=state.session_date.isoformat(), is_open=state.is_open,
        universe_size=len(symbols), scanned=len(scanned), indices=indices, sectors=sectors,
        gainers_5d=gainers, losers_5d=losers, unusual_5d=unusual, highs_52w=highs, lows_52w=lows,
    )


# ------------------------------------------------------------------ compare


def build_compare(db: Session, symbols: list[str], sessions: int, now: datetime) -> schemas.CompareOut:
    state = cal.market_state(now)
    bars_by = get_bars_many(db, symbols, limit=300)
    quotes = get_quotes(db, symbols)
    series: dict[str, dict[date, float]] = {}
    for s in symbols:
        pts = _closes(bars_by.get(s, []), quotes.get(s), state.is_open)[-(sessions + 1):]
        series[s] = dict(pts)
    # Inner-join on dates so every line has a point on every x.
    common = sorted(set.intersection(*(set(d.keys()) for d in series.values()))) if series and all(series.values()) else []
    common = common[-(sessions + 1):]
    out_series: list[schemas.CompareSeries] = []
    rets: dict[str, list[float]] = {}
    for s in symbols:
        closes = [series[s][d] for d in common]
        if len(closes) < 2:
            continue
        base = closes[0]
        rebased = [round(c / base * 100, 3) for c in closes]
        r = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
        rets[s] = r
        mean = sum(r) / len(r)
        vol = math.sqrt(sum((x - mean) ** 2 for x in r) / max(1, len(r) - 1)) * math.sqrt(252)
        peak, mdd = closes[0], 0.0
        for c in closes:
            peak = max(peak, c)
            mdd = min(mdd, c / peak - 1)
        bars = bars_by.get(s, [])
        hi = max((b.high for b in bars[-250:]), default=None)
        lo = min((b.low for b in bars[-250:]), default=None)
        vols = [b.volume for b in bars[-20:] if b.volume]
        meta = db.get(SymbolMeta, s)
        out_series.append(schemas.CompareSeries(
            symbol=s, name=meta.name if meta else (BY_SYMBOL[s].name if s in BY_SYMBOL else s),
            rebased=rebased, last_price=closes[-1], return_pct=closes[-1] / base - 1,
            volatility_annual=vol, max_drawdown=mdd,
            range_position_52w=((closes[-1] - lo) / (hi - lo)) if hi and lo and hi > lo else None,
            avg_volume_20d=(sum(vols) / len(vols)) if vols else None,
            best_day=max(r) if r else None, worst_day=min(r) if r else None,
        ))
    # Correlation of daily log returns.
    syms = [s.symbol for s in out_series]
    corr: list[list[float | None]] = []
    for a in syms:
        row = []
        for b in syms:
            ra, rb = rets[a], rets[b]
            n = min(len(ra), len(rb))
            if n < 5:
                row.append(None)
                continue
            ma, mb = sum(ra[-n:]) / n, sum(rb[-n:]) / n
            cov = sum((x - ma) * (y - mb) for x, y in zip(ra[-n:], rb[-n:]))
            va = math.sqrt(sum((x - ma) ** 2 for x in ra[-n:]))
            vb = math.sqrt(sum((y - mb) ** 2 for y in rb[-n:]))
            row.append(round(cov / (va * vb), 3) if va and vb else None)
        corr.append(row)
    return schemas.CompareOut(generated_at=now, sessions=len(common) - 1 if common else 0,
                              dates=[d.isoformat() for d in common], series=out_series, correlation=corr)


# --------------------------------------------------------------------- news


def build_news_feed(db: Session, user_id: int, now: datetime, days: int = 7) -> schemas.NewsFeedOut:
    """Every headline for every symbol the user follows, newest first, flagged
    'new' against that symbol's own baseline (what they last saw)."""
    wl_syms = set(db.scalars(
        select(WatchlistItem.symbol).join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id).where(Watchlist.user_id == user_id)))
    pin_syms = set(db.scalars(select(Pin.symbol).where(Pin.user_id == user_id)))
    symbols = sorted(wl_syms | pin_syms)
    if not symbols:
        return schemas.NewsFeedOut(generated_at=now, symbols=[], items=[])
    seen_at = {b.symbol: b.committed_seen_at for b in db.scalars(
        select(Baseline).where(Baseline.user_id == user_id, Baseline.symbol.in_(symbols)))}
    names = {m.symbol: m.name for m in db.scalars(select(SymbolMeta).where(SymbolMeta.symbol.in_(symbols)))}
    rows = db.scalars(
        select(NewsItem).where(NewsItem.symbol.in_(symbols), NewsItem.published_at >= now - timedelta(days=days))
        .order_by(NewsItem.published_at.desc()).limit(300)).all()
    items = [schemas.NewsFeedItem(symbol=r.symbol, name=names.get(r.symbol, r.symbol), title=r.title, url=r.url,
                                  source=r.source, published_at=r.published_at,
                                  is_new=(r.symbol in seen_at and r.published_at > seen_at[r.symbol]))
             for r in rows]
    return schemas.NewsFeedOut(generated_at=now, symbols=symbols, items=items)
