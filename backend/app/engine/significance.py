"""Significance engine: turns "price moved" into "this deserves your attention".

Pure functions over plain data — no DB, no clock reads (the caller passes
`now`). That is what makes it unit-testable and what makes the scoring
explainable in one sentence:

    A move matters in proportion to how unusual it is *for that stock*,
    over the number of sessions since *you* last looked.

Concretely: z = ln(price / baseline_price) / (σ_daily · √sessions), with
σ_daily the stock's own trailing 20-session volatility. A 3% move is a 0.9σ
yawn for Suzlon and a 2.7σ event for Hindustan Unilever. Fixed % thresholds
get exactly this wrong, and it is the single most common mistake in
"smart" watchlists.

Discrete events (52-week breach, a user level crossed, a gap open, a long
streak) are layered on top because they carry information a z-score cannot:
they are about *where* the price is, not how far it moved.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime

from ..market import calendar as cal

MIN_SIGMA_DAILY = 0.004      # 0.4%/day floor: indices & mega-caps still produce sane z
FALLBACK_SIGMA_DAILY = 0.018  # used when history is too short to estimate
VOL_WINDOW = 20
RANGE_WINDOW = 250           # ~52 weeks of sessions


@dataclass(frozen=True)
class Bar:
    date: date
    close: float
    high: float
    low: float
    volume: int


@dataclass(frozen=True)
class QuoteIn:
    price: float
    as_of: datetime
    prev_close: float | None = None
    open: float | None = None
    volume: int | None = None


@dataclass(frozen=True)
class BaselineIn:
    price: float
    as_of: datetime      # market time of the price the user saw
    seen_at: datetime    # when they saw it


@dataclass(frozen=True)
class LevelIn:
    id: int
    price: float
    direction: str       # "above" | "below"
    note: str | None = None


@dataclass(frozen=True)
class Reason:
    kind: str            # "move" | "volume" | "range" | "level" | "gap" | "streak" | "info"
    severity: str        # "high" | "medium" | "low"
    text: str


@dataclass
class Assessment:
    tier: str                        # "attention" | "notable" | "quiet"
    score: float
    change_pct: float                # since baseline
    change_abs: float
    sessions: int                    # trading sessions of new information since baseline
    z: float | None
    sigma_daily: float
    volume_ratio: float | None       # today's volume vs 20-session average (session-adjusted)
    day_change_pct: float | None
    range_position_52w: float | None # 0 = at 52w low, 1 = at 52w high
    high_52w: float | None
    low_52w: float | None
    streak: int                      # +n up sessions in a row, -n down
    reasons: list[Reason] = field(default_factory=list)
    levels_crossed: list[int] = field(default_factory=list)  # PriceLevel ids
    low_history: bool = False
    same_print: bool = False         # nothing new to diff against: not a zero move
    market_change_pct: float | None = None   # index move over the same window
    market_share: float | None = None        # fraction of this move explained by the market (0..1)


# ----------------------------------------------------------------- helpers


def sigma_daily(bars: list[Bar]) -> tuple[float, bool]:
    closes = [b.close for b in bars[-(VOL_WINDOW + 1):] if b.close > 0]
    if len(closes) < 8:
        return FALLBACK_SIGMA_DAILY, True
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1)
    return max(MIN_SIGMA_DAILY, math.sqrt(var)), False


def avg_volume(bars: list[Bar]) -> float | None:
    vols = [b.volume for b in bars[-VOL_WINDOW:] if b.volume and b.volume > 0]
    return (sum(vols) / len(vols)) if len(vols) >= 5 else None


def range_52w(bars: list[Bar]) -> tuple[float | None, float | None]:
    window = bars[-RANGE_WINDOW:]
    if len(window) < 20:
        return None, None
    return max(b.high for b in window), min(b.low for b in window)


def streak(bars: list[Bar], price: float, prev_close: float | None, include_today: bool) -> int:
    """Consecutive sessions in one direction, ending at the latest print."""
    closes = [b.close for b in bars]
    if include_today and prev_close:
        closes = closes + [price]
    if len(closes) < 2:
        return 0
    direction = 0
    n = 0
    for i in range(len(closes) - 1, 0, -1):
        d = 1 if closes[i] > closes[i - 1] else -1 if closes[i] < closes[i - 1] else 0
        if d == 0 or (direction and d != direction):
            break
        direction = d
        n += 1
    return direction * n


def fmt_money(x: float) -> str:
    if x >= 1000:
        return f"₹{x:,.0f}"
    return f"₹{x:,.2f}"


def fmt_pct(x: float, signed: bool = True) -> str:
    s = f"{x * 100:+.1f}%" if signed else f"{abs(x) * 100:.1f}%"
    return s


def describe_unusual(z: float | None, change_pct: float, sig: float, sessions: int, market_open: bool,
                     session_fraction: float) -> tuple[str, str, float | None]:
    """The z-score in words. σ means nothing to most people; 'a normal day for
    this stock is about ±0.9%' does."""
    n_eff = max(sessions, 1)
    if market_open and sessions >= 1:
        n_eff = sessions - 1 + max(0.25, session_fraction)
    window = sig * math.sqrt(n_eff)
    span = "a normal day" if sessions <= 1 else f"a normal {sessions}-session stretch"
    if z is None or abs(change_pct) < 0.0005:
        return "Unchanged", f"No real move. {span[0].upper() + span[1:]} for this stock is about ±{fmt_pct(sig if sessions <= 1 else window, signed=False)}.", None
    az = abs(z)
    label = "Ordinary" if az < 1 else "Notable" if az < 2 else "Rare" if az < 3 else "Extreme"
    verb = {"Ordinary": "well within", "Notable": "at the edge of", "Rare": "well outside", "Extreme": "far outside"}[label]
    text = (f"Moved {fmt_pct(change_pct, signed=False)} — {verb} its usual range. "
            f"{span[0].upper() + span[1:]} for this stock is about ±{fmt_pct(window, signed=False)}.")
    return label, text, window


def humanize_since(seen_at: datetime, now: datetime) -> str:
    delta = now - seen_at
    mins = delta.total_seconds() / 60
    if mins < 2:
        return "just now"
    if mins < 60:
        return f"{int(mins)} min ago"
    hours = mins / 60
    if hours < 12:
        return f"{int(hours)}h ago"
    # Beyond half a day, people think in calendar days, not 24h buckets.
    days = (cal._ist(now).date() - cal._ist(seen_at).date()).days
    if days <= 0:
        return "earlier today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return cal._ist(seen_at).strftime("%A")
    if days < 14:
        return "last week"
    return f"{cal._ist(seen_at):%d %b}"


# ------------------------------------------------------------------ assess


def assess(
    bars: list[Bar],
    quote: QuoteIn,
    baseline: BaselineIn,
    levels: list[LevelIn],
    now: datetime,
    *,
    market_open: bool,
    session_fraction: float,
    market_change_pct: float | None = None,
) -> Assessment:
    reasons: list[Reason] = []
    sig, low_hist = sigma_daily(bars)

    # ---- 1. the move since *you* looked ------------------------------
    change_abs = quote.price - baseline.price
    change_pct = (quote.price / baseline.price - 1) if baseline.price > 0 else 0.0
    sessions = cal.sessions_between(baseline.as_of, quote.as_of)
    same_print = quote.as_of <= baseline.as_of
    z: float | None = None
    if not same_print and abs(change_pct) > 1e-9:
        # Intraday: part of a session has passed since they looked.
        n_eff = sessions if sessions >= 1 else 0.5
        if market_open and sessions >= 1:
            n_eff = sessions - 1 + max(0.25, session_fraction)
        z = math.log(quote.price / baseline.price) / (sig * math.sqrt(n_eff))

    # ---- 2. volume ---------------------------------------------------
    volume_ratio: float | None = None
    avg_v = avg_volume(bars)
    if quote.volume and avg_v:
        expected = avg_v * (max(0.15, session_fraction) if market_open else 1.0)
        volume_ratio = quote.volume / expected

    # ---- 3. position: 52-week range ---------------------------------
    high_52w, low_52w = range_52w(bars)
    range_pos = None
    if high_52w and low_52w and high_52w > low_52w:
        range_pos = min(1.0, max(0.0, (quote.price - low_52w) / (high_52w - low_52w)))
    at_high = high_52w is not None and quote.price >= high_52w
    at_low = low_52w is not None and quote.price <= low_52w

    # ---- 4. gap open (only if it happened after they last looked) ----
    gap_pct = None
    session_open = cal._utc_naive(cal._ist(quote.as_of).date(), cal.OPEN)
    gap_is_new = baseline.as_of < session_open   # they haven't seen this session's open yet
    if quote.open and quote.prev_close and quote.prev_close > 0 and not same_print and gap_is_new:
        g = quote.open / quote.prev_close - 1
        if abs(g) >= 2 * sig:
            gap_pct = g

    # ---- 5. streak ---------------------------------------------------
    stk = streak(bars, quote.price, quote.prev_close, include_today=market_open)

    # ---- 6. user levels ----------------------------------------------
    # A level counts as crossed if it lies between what you saw and what it is
    # now — in either direction. "Fell through 3400" and "climbed back above
    # 3400" are both news; the direction you set only changes the wording.
    crossed: list[int] = []
    lo, hi = sorted((baseline.price, quote.price))
    for lv in levels:
        if lo < lv.price <= hi or lo <= lv.price < hi:
            if lv.price != baseline.price or quote.price != baseline.price:
                crossed.append(lv.id)

    day_change_pct = (quote.price / quote.prev_close - 1) if quote.prev_close else None

    # ---- reasons, most important first -------------------------------
    since_txt = humanize_since(baseline.seen_at, now)
    sess_txt = "today" if sessions <= 1 else f"over {sessions} sessions"

    if same_print:
        reasons.append(Reason("info", "low", "No new prints since you last looked" + (" — market closed" if not market_open else "")))
    elif abs(change_pct) < 0.0005:
        reasons.append(Reason("info", "low", f"Unchanged since you looked ({since_txt})"))
    elif z is not None:
        az = abs(z)
        direction = "up" if change_pct > 0 else "down"
        if az >= 2:
            reasons.append(Reason("move", "high",
                f"{direction.capitalize()} {fmt_pct(change_pct, signed=False)} since you looked ({since_txt}) — "
                f"a {az:.1f}σ move for this stock {sess_txt}"))
        elif az >= 1:
            reasons.append(Reason("move", "medium",
                f"{direction.capitalize()} {fmt_pct(change_pct, signed=False)} since {since_txt} ({az:.1f}σ, {sess_txt})"))
        else:
            reasons.append(Reason("move", "low",
                f"{fmt_pct(change_pct)} since {since_txt} — ordinary for this stock ({az:.1f}σ)"))

    for lv_id in crossed:
        lv = next(l for l in levels if l.id == lv_id)
        note = f" — {lv.note}" if lv.note else ""
        verb = "Fell through" if quote.price < baseline.price else "Rose through"
        reasons.append(Reason("level", "high", f"{verb} your {fmt_money(lv.price)} level{note}"))

    if at_high:
        reasons.append(Reason("range", "high", f"At a 52-week high ({fmt_money(quote.price)})"))
    elif at_low:
        reasons.append(Reason("range", "high", f"At a 52-week low ({fmt_money(quote.price)})"))
    elif range_pos is not None and high_52w and range_pos >= 0.97:
        reasons.append(Reason("range", "low", f"Within {fmt_pct(1 - quote.price / high_52w, signed=False)} of its 52-week high"))
    elif range_pos is not None and low_52w and range_pos <= 0.03:
        reasons.append(Reason("range", "low", f"Within {fmt_pct(quote.price / low_52w - 1, signed=False)} of its 52-week low"))

    if volume_ratio is not None and volume_ratio >= 2:
        reasons.append(Reason("volume", "medium" if volume_ratio < 3 else "high",
            f"{volume_ratio:.1f}× normal volume" + (" so far today" if market_open else "")))

    if gap_pct is not None:
        reasons.append(Reason("gap", "medium", f"Gapped {'up' if gap_pct > 0 else 'down'} {fmt_pct(gap_pct, signed=False)} at the open"))

    if abs(stk) >= 4:
        reasons.append(Reason("streak", "low", f"{abs(stk)} straight {'up' if stk > 0 else 'down'} sessions"))

    # ---- 7. how much of this is just the market? -----------------------
    # A stock down 3% on a day Nifty fell 2.5% is not news about the stock.
    market_share: float | None = None
    against_market = False
    if market_change_pct is not None and not same_print and abs(change_pct) >= 0.005 and abs(market_change_pct) >= 0.005:
        if (market_change_pct > 0) == (change_pct > 0):
            market_share = max(0.0, min(1.0, market_change_pct / change_pct))
            if market_share >= 0.6:
                reasons.append(Reason("market", "low",
                    f"Nifty 50 moved {fmt_pct(market_change_pct)} over the same period — "
                    f"{'most' if market_share < 0.9 else 'nearly all'} of this is the market, not the stock"))
        elif abs(market_change_pct) >= 0.01:
            against_market = True
            reasons.append(Reason("market", "medium",
                f"Moved {'up' if change_pct > 0 else 'down'} while Nifty 50 went {fmt_pct(market_change_pct)} — against the market"))

    if low_hist:
        reasons.append(Reason("info", "low", "Limited price history — volatility estimate is a default"))

    # ---- score & tier --------------------------------------------------
    az = abs(z) if z is not None else 0.0
    score = az
    if volume_ratio:
        score += min(2.0, 0.5 * max(0.0, volume_ratio - 1))
    if at_high or at_low:
        score += 1.5
    if crossed:
        score += 2.0
    if gap_pct is not None:
        score += 1.0
    if abs(stk) >= 4:
        score += 0.5

    if crossed or at_high or at_low or az >= 2 or (az >= 1.5 and (volume_ratio or 0) >= 2):
        tier = "attention"
    elif az >= 1 or (volume_ratio or 0) >= 2 or gap_pct is not None or abs(stk) >= 4:
        tier = "notable"
    else:
        tier = "quiet"
    # A move that is mostly the whole market earns one notch less attention —
    # unless something stock-specific (a level, a 52-week breach) also fired.
    if market_share is not None and market_share >= 0.7 and not (crossed or at_high or at_low):
        tier = {"attention": "notable", "notable": "quiet", "quiet": "quiet"}[tier]
        score *= 0.6
    if against_market and tier == "quiet" and az >= 0.7:
        tier = "notable"

    return Assessment(
        tier=tier,
        score=round(score, 3),
        change_pct=change_pct,
        change_abs=change_abs,
        sessions=sessions,
        z=round(z, 3) if z is not None else None,
        sigma_daily=sig,
        volume_ratio=round(volume_ratio, 2) if volume_ratio is not None else None,
        day_change_pct=day_change_pct,
        range_position_52w=range_pos,
        high_52w=high_52w,
        low_52w=low_52w,
        streak=stk,
        reasons=reasons,
        levels_crossed=crossed,
        low_history=low_hist,
        same_print=same_print,
        market_change_pct=market_change_pct,
        market_share=market_share,
    )
