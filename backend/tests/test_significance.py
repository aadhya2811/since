"""The scoring engine is the product. These tests pin down its behaviour."""
import math
from datetime import date, datetime, timedelta

from app.engine.significance import Bar, BaselineIn, LevelIn, QuoteIn, assess, sigma_daily, streak

# Wednesday 2 Sep 2026, 13:00 IST = 07:30 UTC (market open)
NOW = datetime(2026, 9, 2, 7, 30)
YESTERDAY_CLOSE = datetime(2026, 9, 1, 10, 0)   # Tue 15:30 IST
LAST_WEEK_CLOSE = datetime(2026, 8, 26, 10, 0)  # Wed, 5 sessions before Wed 2 Sep


def make_bars(n: int, price: float, daily_vol: float, end: date = date(2026, 9, 1), seed: int = 1) -> list[Bar]:
    """Deterministic alternating-return series with a chosen realised vol."""
    bars = []
    d = end
    closes = []
    p = price
    for i in range(n):
        closes.append(p)
        p = p / math.exp(daily_vol if i % 2 == 0 else -daily_vol)
    closes.reverse()
    days = []
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    for dd, c in zip(days, closes):
        bars.append(Bar(dd, c, c * 1.10, c * 0.90, 1_000_000))  # wide range: a few % is not a 52w breach
    return bars


def run(bars, price, baseline_price, baseline_as_of=YESTERDAY_CLOSE, levels=(), volume=None, prev_close=None, open_=None,
        market_open=True, frac=0.6, quote_as_of=NOW):
    q = QuoteIn(price=price, as_of=quote_as_of, prev_close=prev_close or bars[-1].close, open=open_, volume=volume)
    b = BaselineIn(price=baseline_price, as_of=baseline_as_of, seen_at=baseline_as_of)
    return assess(bars, q, b, list(levels), NOW, market_open=market_open, session_fraction=frac)


def test_same_percent_move_is_judged_by_the_stocks_own_volatility():
    calm = make_bars(60, 1000, 0.006)     # ~0.6%/day
    wild = make_bars(60, 1000, 0.035)     # ~3.5%/day
    a_calm = run(calm, 1030, 1000)        # +3% in one session
    a_wild = run(wild, 1030, 1000)
    assert a_calm.tier == "attention"
    assert a_wild.tier != "attention"          # same 3%, ordinary for this name
    assert abs(a_calm.z) > abs(a_wild.z) * 3
    # ...and after a full session it drops out of view entirely
    assert run(wild, 1030, 1000, market_open=False, frac=1.0).tier == "quiet"


def test_move_is_scaled_by_sessions_elapsed():
    bars = make_bars(60, 1000, 0.01)
    one_day = run(bars, 1040, 1000, baseline_as_of=YESTERDAY_CLOSE)
    one_week = run(bars, 1040, 1000, baseline_as_of=LAST_WEEK_CLOSE)
    assert one_day.sessions == 1
    assert one_week.sessions == 5
    assert abs(one_day.z) > abs(one_week.z)
    assert one_day.tier == "attention"
    assert one_week.tier in ("notable", "quiet")


def test_no_new_print_means_no_move_reason():
    bars = make_bars(60, 1000, 0.01)
    a = run(bars, 1000, 1000, baseline_as_of=NOW, quote_as_of=NOW)
    assert a.z is None
    assert a.tier == "quiet"
    assert any(r.kind == "info" for r in a.reasons)


def test_level_crossed_in_either_direction_and_not_otherwise():
    bars = make_bars(60, 1000, 0.01)
    lv = LevelIn(id=7, price=980, direction="below", note="buy zone")
    down = run(bars, 970, 1000, levels=[lv])
    assert 7 in down.levels_crossed and down.tier == "attention"
    assert any("Fell through" in r.text and "buy zone" in r.text for r in down.reasons)
    up = run(bars, 990, 970, levels=[lv])
    assert 7 in up.levels_crossed
    assert any("Rose through" in r.text for r in up.reasons)
    untouched = run(bars, 1005, 1000, levels=[lv])
    assert untouched.levels_crossed == []


def test_52_week_high_is_attention_even_on_a_small_move():
    bars = make_bars(260, 1000, 0.01)
    top = max(b.high for b in bars)
    a = run(bars, top * 1.001, top * 0.999)   # tiny move, but a new high
    assert a.tier == "attention"
    assert any(r.kind == "range" and "52-week high" in r.text for r in a.reasons)
    assert a.range_position_52w == 1.0


def test_volume_ratio_is_session_adjusted_while_open():
    bars = make_bars(60, 1000, 0.01)          # avg volume 1,000,000
    a = run(bars, 1001, 1000, volume=1_200_000, frac=0.5, market_open=True)
    assert a.volume_ratio == 2.4               # 1.2M vs 0.5M expected so far
    b = run(bars, 1001, 1000, volume=1_200_000, frac=1.0, market_open=False)
    assert b.volume_ratio == 1.2
    assert a.tier == "notable" and b.tier == "quiet"


def test_gap_open_is_reported_only_when_large():
    bars = make_bars(60, 1000, 0.01)
    prev = bars[-1].close
    gap = run(bars, prev * 0.96, prev, open_=prev * 0.965)
    assert any(r.kind == "gap" for r in gap.reasons)
    no_gap = run(bars, prev * 1.002, prev, open_=prev * 1.001)
    assert not any(r.kind == "gap" for r in no_gap.reasons)
    # A gap the user already saw (baseline taken mid-session, after the open) is not news.
    seen_already = run(bars, prev * 0.96, prev * 0.965, open_=prev * 0.965, baseline_as_of=datetime(2026, 9, 2, 5, 0))
    assert not any(r.kind == "gap" for r in seen_already.reasons)


def test_short_history_falls_back_to_default_sigma_and_says_so():
    bars = make_bars(5, 1000, 0.01)
    a = run(bars, 1020, 1000)
    assert a.low_history
    assert any("Limited price history" in r.text for r in a.reasons)


def test_sigma_has_a_floor_so_indices_dont_explode():
    flat = make_bars(60, 1000, 0.0001)
    sig, low = sigma_daily(flat)
    assert not low and sig >= 0.004


def test_streak_counts_direction_runs():
    closes = [100, 101, 102, 103, 104]
    bars = [Bar(date(2026, 8, 24 + i), c, c, c, 1) for i, c in enumerate(closes)]
    assert streak(bars, 105, 104, include_today=True) == 5
    assert streak(bars, 103, 104, include_today=True) == -1
    assert streak(bars, 0, None, include_today=False) == 4


def test_reasons_are_ordered_move_first_then_events():
    bars = make_bars(260, 1000, 0.01)
    top = max(b.high for b in bars)
    a = run(bars, top * 1.03, top * 0.98, levels=[LevelIn(1, top, "above")], volume=5_000_000)
    kinds = [r.kind for r in a.reasons]
    assert kinds[0] == "move"
    assert kinds.index("level") < kinds.index("volume")
