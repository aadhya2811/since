"""Calendar, snapshot store conflict rules, circuit breaker + fallback."""
from datetime import date, datetime, timedelta

import pytest

from app.db import Base, SessionLocal, engine
from app.market import calendar as cal
from app.market.provider import BarData, ProviderError, QuoteData, SymbolNotFound
from app.market.resilient import Breaker, ResilientProvider
from app.market.simulated import SimulatedProvider
from app.market.store import get_bars, upsert_bars, upsert_quote
from app.models import Quote

# ----------------------------------------------------------------- calendar


def test_market_state_phases():
    # Wed 2 Sep 2026: 08:00 IST pre, 12:00 open, 16:00 closed  (IST = UTC+5:30)
    assert cal.market_state(datetime(2026, 9, 2, 2, 30)).phase == "pre"
    assert cal.market_state(datetime(2026, 9, 2, 6, 30)).is_open
    assert cal.market_state(datetime(2026, 9, 2, 10, 30)).phase == "closed"
    sat = cal.market_state(datetime(2026, 9, 5, 6, 30))
    assert not sat.is_open and sat.session_date == date(2026, 9, 4)
    assert sat.next_open == datetime(2026, 9, 7, 3, 45)


def test_sessions_between_skips_weekends_and_holidays():
    fri_close = datetime(2026, 9, 4, 10, 0)
    mon_open_plus = datetime(2026, 9, 7, 4, 30)
    assert cal.sessions_between(fri_close, fri_close + timedelta(hours=20)) == 0     # Saturday morning
    assert cal.sessions_between(fri_close, mon_open_plus) == 1
    # 14 Aug (Fri) close → 17 Aug (Mon) noon: 15 Aug is a holiday and a Saturday anyway; 1 session
    assert cal.sessions_between(datetime(2026, 8, 14, 10, 0), datetime(2026, 8, 17, 6, 30)) == 1
    # 1 Oct close → 5 Oct noon: 2 Oct holiday (Fri), weekend, Mon = 1 session
    assert cal.sessions_between(datetime(2026, 10, 1, 10, 0), datetime(2026, 10, 5, 6, 30)) == 1
    assert cal.sessions_between(datetime(2026, 8, 26, 10, 0), datetime(2026, 9, 2, 7, 30)) == 5


# -------------------------------------------------------------------- store


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    s = SessionLocal()
    yield s
    s.close()


def q(price, as_of, source="yahoo", symbol="X.NS"):
    return QuoteData(symbol=symbol, price=price, as_of=as_of, source=source)


def test_quote_never_moves_backwards_in_market_time(db):
    t = datetime(2026, 9, 2, 7, 0)
    assert upsert_quote(db, q(100, t))
    assert not upsert_quote(db, q(90, t - timedelta(minutes=5)))   # late-arriving old print
    assert db.get(Quote, "X.NS").price == 100
    assert upsert_quote(db, q(101, t + timedelta(minutes=1)))
    assert db.get(Quote, "X.NS").price == 101


def test_same_print_conflict_primary_wins(db):
    t = datetime(2026, 9, 2, 7, 0)
    upsert_quote(db, q(100, t, source="yahoo"), primary_source="yahoo")
    assert not upsert_quote(db, q(99, t, source="simulated"), primary_source="yahoo")
    assert db.get(Quote, "X.NS").price == 100
    # ...but if the fallback is what we have, a primary print at the same time replaces it.
    upsert_quote(db, q(50, t, source="simulated", symbol="Y.NS"), primary_source="yahoo")
    upsert_quote(db, q(51, t, source="yahoo", symbol="Y.NS"), primary_source="yahoo")
    assert db.get(Quote, "Y.NS").price == 51


def test_bars_upsert_is_idempotent_and_corrects(db):
    bars = [BarData(date(2026, 9, 1), 1, 2, 0.5, 1.5, 10), BarData(date(2026, 9, 2), 1.5, 2, 1, 1.8, 20)]
    assert upsert_bars(db, "X.NS", bars) == 2
    assert upsert_bars(db, "X.NS", bars) == 0
    fixed = [BarData(date(2026, 9, 2), 1.5, 2, 1, 1.9, 25)]
    assert upsert_bars(db, "X.NS", fixed) == 1
    rows = get_bars(db, "X.NS")
    assert len(rows) == 2 and rows[-1].close == 1.9


# --------------------------------------------------------- circuit breaker


def test_breaker_opens_after_threshold_and_half_opens_after_reset():
    clock = [0.0]
    b = Breaker(threshold=2, reset_seconds=10, _clock=lambda: clock[0])
    assert b.state == "closed"
    b.record_failure(Exception("x"))
    assert b.state == "closed" and b.allow()
    b.record_failure(Exception("y"))
    assert b.state == "open" and not b.allow()
    clock[0] = 11
    assert b.state == "half-open" and b.allow()
    b.record_success()
    assert b.state == "closed"


@pytest.mark.asyncio
async def test_resilient_provider_fails_over_and_reports_degraded():
    primary, fallback = SimulatedProvider(), SimulatedProvider()
    primary.name, fallback.name = "primary", "fallback"
    rp = ResilientProvider([primary, fallback], threshold=2, reset_seconds=1000)
    assert (await rp.get_quotes(["TCS.NS"]))["TCS.NS"].source == "primary"
    assert not rp.status()["degraded"]

    primary.fail = True
    for _ in range(2):
        await rp.get_quotes(["TCS.NS"])            # served by fallback, primary failures counted
    assert rp.breakers["primary"].state == "open"
    calls_before = primary.calls
    await rp.get_quotes(["TCS.NS"])
    assert primary.calls == calls_before             # open breaker: primary skipped entirely
    st = rp.status()
    assert st["degraded"] and st["active"] == "fallback"

    fallback.fail = True
    with pytest.raises(ProviderError):
        await rp.get_quotes(["TCS.NS"])


@pytest.mark.asyncio
async def test_symbol_not_found_does_not_trip_breaker_or_fall_back():
    primary, fallback = SimulatedProvider(), SimulatedProvider()
    primary.name, fallback.name = "primary", "fallback"
    primary.unknown = {"NOPE.NS"}
    rp = ResilientProvider([primary, fallback], threshold=2, reset_seconds=1000)
    for _ in range(3):
        with pytest.raises(SymbolNotFound):
            await rp.get_daily_bars("NOPE.NS")
    assert rp.breakers["primary"].state == "closed"
    assert rp.breakers["primary"].failures == 0
    assert fallback.calls == 0                         # never answered with made-up data
    assert not rp.status()["degraded"]
