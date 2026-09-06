"""The Yahoo payload parser, against synthetic responses.

This is the only place in the codebase where a number can be *wrong* rather
than merely missing: everything downstream is arithmetic over what lands here.
So these tests assert on exact values, and every fixture is a hand-built
payload shaped like a real Yahoo v8 chart response — no network, no recorded
cassette that could drift.

The bug these exist to prevent actually happened: `chartPreviousClose` is the
close before the *chart range*, so on a 5-day range it is five sessions old.
Using it made "% today" silently wrong for every stock.
"""
from datetime import datetime, timezone

import httpx
import pytest

from app.market.provider import ProviderError, QuoteData, SymbolNotFound
from app.market.yahoo import YahooProvider


def epoch(y, m, d, hh=10, mm=0) -> int:
    return int(datetime(y, m, d, hh, mm, tzinfo=timezone.utc).timestamp())


def chart_payload(*, price=1500.0, as_of=None, ts=None, opens=None, highs=None, lows=None,
                  closes=None, volumes=None, meta_extra=None) -> dict:
    ts = ts if ts is not None else [epoch(2025, 6, 2), epoch(2025, 6, 3), epoch(2025, 6, 4), epoch(2025, 6, 5)]
    n = len(ts)
    meta = {
        "regularMarketPrice": price,
        "regularMarketTime": as_of if as_of is not None else ts[-1],
        "regularMarketDayHigh": 1520.0,
        "regularMarketDayLow": 1470.0,
        "regularMarketVolume": 1234567,
        "chartPreviousClose": 1000.0,     # deliberately stale & wrong — must be ignored
        "longName": "Test Industries Ltd",
        "currency": "INR",
        "exchangeDataDelayedBy": 15,
    }
    meta.update(meta_extra or {})
    return {"chart": {"error": None, "result": [{
        "meta": meta,
        "timestamp": ts,
        "indicators": {"quote": [{
            "open": opens if opens is not None else [1400.0] * n,
            "high": highs if highs is not None else [1450.0] * n,
            "low": lows if lows is not None else [1380.0] * n,
            "close": closes if closes is not None else [1410.0, 1420.0, 1430.0, 1440.0],
            "volume": volumes if volumes is not None else [1000] * n,
        }]},
    }]}}


def provider_with(handler) -> tuple[YahooProvider, httpx.AsyncClient]:
    return YahooProvider(), httpx.AsyncClient(transport=httpx.MockTransport(handler))


def respond(payload, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)
    return handler


async def quote_from(payload, status=200, symbol="TEST.NS") -> QuoteData | None:
    p, client = provider_with(respond(payload, status))
    async with client:
        return await p._quote(client, symbol)


# ------------------------------------------------------- the prev_close bug


@pytest.mark.asyncio
async def test_prev_close_comes_from_yesterdays_row_not_chart_previous_close():
    q = await quote_from(chart_payload())
    assert q is not None
    # 4th row is the print's own session; the 3rd row's close is "yesterday".
    assert q.prev_close == 1430.0
    assert q.prev_close != 1000.0          # chartPreviousClose, five sessions stale
    assert q.open == 1400.0                # today's open, from the row — not meta


@pytest.mark.asyncio
async def test_prev_close_skips_null_rows_for_holidays_and_halts():
    """Yahoo emits null rows for holidays. Yesterday is the last row that has
    a close, not the last row that exists."""
    q = await quote_from(chart_payload(closes=[1410.0, 1420.0, None, 1440.0]))
    assert q.prev_close == 1420.0


@pytest.mark.asyncio
async def test_falls_back_to_meta_previous_close_only_when_no_row_matches():
    """If the print's date is not in the daily rows at all we cannot derive it,
    so we take meta's own previousClose — never chartPreviousClose."""
    q = await quote_from(chart_payload(
        as_of=epoch(2025, 6, 20),          # a date absent from the rows
        meta_extra={"regularMarketPreviousClose": 1499.0}))
    assert q.prev_close == 1499.0


@pytest.mark.asyncio
async def test_day_change_is_computed_from_the_derived_prev_close():
    """The number the user actually reads. 1500 against 1430 is +4.9%, and
    against the stale 1000 it would have read +50%."""
    q = await quote_from(chart_payload(price=1500.0))
    assert round(q.price / q.prev_close - 1, 4) == 0.049


# ---------------------------------------------------- vendor-declared delay


@pytest.mark.asyncio
async def test_vendor_declared_delay_is_carried_through_verbatim():
    assert (await quote_from(chart_payload())).delay_minutes == 15
    assert (await quote_from(chart_payload(meta_extra={"exchangeDataDelayedBy": 0}))).delay_minutes == 0


@pytest.mark.asyncio
async def test_missing_delay_assumes_delayed_never_live():
    """Absent a statement from the vendor we assume 15 minutes. The failure
    mode we refuse is labelling a stale price 'Live'."""
    p = chart_payload()
    del p["chart"]["result"][0]["meta"]["exchangeDataDelayedBy"]
    assert (await quote_from(p)).delay_minutes == 15


# ------------------------------------------------- absent and broken inputs


@pytest.mark.asyncio
async def test_a_quote_without_a_price_is_dropped_not_defaulted():
    p = chart_payload()
    del p["chart"]["result"][0]["meta"]["regularMarketPrice"]
    assert await quote_from(p) is None


@pytest.mark.asyncio
async def test_unknown_ticker_raises_symbol_not_found_not_provider_error():
    """The distinction matters: SymbolNotFound must not trip the circuit
    breaker or trigger failover — one bad ticker is not an outage."""
    p, client = provider_with(respond({"chart": {"error": {"code": "Not Found"}, "result": None}}, 404))
    async with client:
        with pytest.raises(SymbolNotFound):
            await p._chart(client, "NOPE.NS", "5d", "1d")


@pytest.mark.asyncio
async def test_rate_limit_and_server_errors_are_provider_errors():
    for status in (429, 500, 503):
        p, client = provider_with(respond({}, status))
        async with client:
            with pytest.raises(ProviderError):
                await p._chart(client, "TEST.NS", "5d", "1d")


@pytest.mark.asyncio
async def test_malformed_payload_is_an_error_not_a_silent_zero():
    def handler(request):
        return httpx.Response(200, text="<html>not json</html>")
    p, client = YahooProvider(), httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with client:
        with pytest.raises(ProviderError):
            await p._chart(client, "TEST.NS", "5d", "1d")


# ------------------------------------------------------------------- bars


@pytest.mark.asyncio
async def test_bars_drop_null_rows_and_keep_real_ones():
    payload = chart_payload(
        ts=[epoch(2025, 6, 2), epoch(2025, 6, 3), epoch(2025, 6, 4)],
        opens=[100.0, None, 102.0], highs=[105.0, None, 107.0],
        lows=[99.0, None, 101.0], closes=[104.0, None, 106.0], volumes=[10, None, 30])
    p, client = provider_with(respond(payload))
    p_get = YahooProvider()

    async def fake_chart(_client, symbol, rng, interval):
        return payload["chart"]["result"][0]

    p_get._chart = fake_chart  # type: ignore[method-assign]
    bars = await p_get.get_daily_bars("TEST.NS", days=365)
    await client.aclose()
    assert [b.close for b in bars] == [104.0, 106.0]
    assert [b.volume for b in bars] == [10, 30]
    assert all(b.high >= b.low for b in bars)


# ----------------------------------------------------- fundamentals payload


def summary_payload(**over) -> dict:
    stats = {
        "trailingEps": {"raw": 42.5, "fmt": "42.50"},
        "priceToBook": {"raw": 3.2},
        "bookValue": {"raw": 468.75},
        "forwardPE": {"raw": 21.0},
        "mostRecentQuarter": {"raw": epoch(2025, 6, 30)},
    }
    fin = {
        "returnOnEquity": {"raw": 0.1432},        # a fraction, 14.32%
        "debtToEquity": {"raw": 38.4},            # a PERCENTAGE, per Yahoo
        "profitMargins": {"raw": 0.087},
        "revenueGrowth": {"raw": 0.114},
    }
    summ = {"trailingPE": {"raw": 24.6}, "dividendYield": {"raw": 0.0072}, "beta": {"raw": 1.13},
            "marketCap": {"raw": 1.42e13}}
    price = {"marketCap": {"raw": 1.42e13}}
    blocks = {"defaultKeyStatistics": stats, "financialData": fin, "summaryDetail": summ, "price": price}
    blocks.update(over)
    return {"quoteSummary": {"error": None, "result": [blocks]}}


async def funda_from(payload, status=200, symbol="TEST.NS"):
    p = YahooProvider()
    p._crumb = "abc123"
    client = httpx.AsyncClient(transport=httpx.MockTransport(respond(payload, status)))
    async with client:
        return await p._fundamentals_one(client, symbol, "abc123")


@pytest.mark.asyncio
async def test_fundamentals_are_parsed_with_their_units_intact():
    f = await funda_from(summary_payload())
    assert f is not None
    assert f.pe_trailing == 24.6 and f.pe_forward == 21.0
    assert f.eps_trailing == 42.5 and f.price_to_book == 3.2 and f.book_value == 468.75
    assert f.roe == 0.1432                 # fraction — the UI multiplies by 100 once, not twice
    assert f.dividend_yield == 0.0072
    assert f.debt_to_equity == 38.4        # Yahoo's own percentage, carried through unchanged
    assert f.market_cap == 1.42e13
    assert f.as_of is not None and f.as_of.date().isoformat() == "2025-06-30"


@pytest.mark.asyncio
async def test_absent_fields_are_none_and_never_zero():
    """The failure that would put a fake "P/E 0.0" on screen. A loss-making
    company has no trailing P/E, and Yahoo signals that with an empty dict."""
    f = await funda_from(summary_payload(
        summaryDetail={"trailingPE": {}, "dividendYield": {}},
        financialData={"returnOnEquity": {"raw": -0.08}},
        price={"marketCap": {"raw": 5.0e11}}))
    assert f.pe_trailing is None and f.dividend_yield is None
    assert f.roe == -0.08                  # a real negative ROE is kept, not clamped
    assert f.profit_margin is None         # absent from the block entirely
    assert f.market_cap == 5.0e11


@pytest.mark.asyncio
async def test_a_response_with_nothing_usable_is_not_stored_as_a_row():
    """An all-empty answer must return None. Storing it would look like a
    successful fetch and stop us ever retrying the symbol."""
    assert await funda_from({"quoteSummary": {"error": None, "result": [
        {"defaultKeyStatistics": {}, "financialData": {}, "summaryDetail": {}, "price": {}}]}}) is None


@pytest.mark.asyncio
async def test_string_and_boolean_junk_is_rejected_rather_than_coerced():
    f = await funda_from(summary_payload(
        summaryDetail={"trailingPE": "N/A", "dividendYield": True, "marketCap": {"raw": 1.0e11}}))
    assert f.pe_trailing is None and f.dividend_yield is None


@pytest.mark.asyncio
async def test_a_rejected_crumb_clears_it_so_the_next_cycle_refetches():
    p = YahooProvider()
    p._crumb = "stale"
    client = httpx.AsyncClient(transport=httpx.MockTransport(respond({}, 401)))
    async with client:
        with pytest.raises(ProviderError):
            await p._fundamentals_one(client, "TEST.NS", "stale")
    assert p._crumb is None


@pytest.mark.asyncio
async def test_no_crumb_means_no_fundamentals_not_an_exception():
    """The whole feature is optional. If Yahoo will not hand over a crumb the
    app must carry on serving prices, which is what it is actually for."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="<html>nope</html>")   # crumb endpoint refuses

    import app.market.yahoo as y
    real_client_cls = httpx.AsyncClient          # captured before patching, or we recurse
    p = YahooProvider()
    y.httpx.AsyncClient = lambda **kw: real_client_cls(transport=httpx.MockTransport(handler))
    try:
        assert await p.get_fundamentals(["TEST.NS"]) == {}
    finally:
        y.httpx.AsyncClient = real_client_cls


@pytest.mark.asyncio
async def test_an_html_error_page_is_never_mistaken_for_a_crumb():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<!DOCTYPE html><html>Sign in to continue</html>")
    p = YahooProvider()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with client:
        assert await p._get_crumb(client) is None
