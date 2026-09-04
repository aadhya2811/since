"""NSE trading calendar. Pure functions, no I/O.

Why this exists: "what changed since you last looked" must be measured in
*trading sessions*, not wall-clock days. Friday-evening to Monday-morning is
zero sessions of new information, and a 2% move over one session means
something very different from 2% over five. It also lets the scheduler stop
polling a closed market.

Holidays are a config list: exchanges publish them yearly and they belong in
data, not code. A missed holiday degrades to "one extra session counted" —
never to wrong prices.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
OPEN = time(9, 15)
CLOSE = time(15, 30)

# Fixed-date national holidays. Lunar-calendar holidays (Holi, Diwali, Eid,
# ...) shift yearly and should be appended per year from the NSE circular.
HOLIDAYS: set[date] = {
    date(2026, 1, 26),
    date(2026, 8, 15),
    date(2026, 10, 2),
    date(2026, 12, 25),
}


@dataclass(frozen=True)
class MarketState:
    is_open: bool
    phase: str            # "open" | "pre" | "closed"
    session_date: date    # the session whose prices we are showing
    last_close: datetime  # UTC naive: most recent completed (or current) session close
    next_open: datetime   # UTC naive


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS


def _ist(dt_utc_naive: datetime) -> datetime:
    return dt_utc_naive.replace(tzinfo=timezone.utc).astimezone(IST)


def _utc_naive(d: date, t: time) -> datetime:
    return datetime.combine(d, t, IST).astimezone(timezone.utc).replace(tzinfo=None)


def previous_trading_day(d: date) -> date:
    d = d - timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def next_trading_day(d: date) -> date:
    d = d + timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def market_state(now_utc: datetime) -> MarketState:
    now = _ist(now_utc)
    today = now.date()
    if is_trading_day(today):
        if now.time() < OPEN:
            prev = previous_trading_day(today)
            return MarketState(False, "pre", prev, _utc_naive(prev, CLOSE), _utc_naive(today, OPEN))
        if now.time() <= CLOSE:
            return MarketState(True, "open", today, _utc_naive(today, CLOSE), _utc_naive(next_trading_day(today), OPEN))
        return MarketState(False, "closed", today, _utc_naive(today, CLOSE), _utc_naive(next_trading_day(today), OPEN))
    prev = previous_trading_day(today)
    return MarketState(False, "closed", prev, _utc_naive(prev, CLOSE), _utc_naive(next_trading_day(today), OPEN))


def sessions_between(start_utc: datetime, end_utc: datetime) -> int:
    """Number of trading sessions that have *contributed new information*
    between two instants. A session counts if its close is after `start` and
    its open is before `end`. Minimum 0."""
    if end_utc <= start_utc:
        return 0
    d = _ist(start_utc).date()
    end_ist = _ist(end_utc)
    count = 0
    while d <= end_ist.date():
        if is_trading_day(d):
            s_open, s_close = _utc_naive(d, OPEN), _utc_naive(d, CLOSE)
            if s_close > start_utc and s_open < end_utc:
                count += 1
        d += timedelta(days=1)
    return count


def session_fraction_elapsed(now_utc: datetime) -> float:
    """0..1: how much of today's session has traded. 1.0 when closed."""
    st = market_state(now_utc)
    if not st.is_open:
        return 1.0
    now = _ist(now_utc)
    total = (CLOSE.hour * 60 + CLOSE.minute) - (OPEN.hour * 60 + OPEN.minute)
    done = (now.hour * 60 + now.minute) - (OPEN.hour * 60 + OPEN.minute)
    return max(0.05, min(1.0, done / total))
