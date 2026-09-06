"""Analyst memory.

The engine tests are the interesting ones: a prompt that fires too eagerly is
worse than no prompt at all, because it trains the user to dismiss without
reading. So these pin down exactly when we are allowed to interrupt.
"""
from datetime import date, datetime, timedelta

from app.engine.significance import Bar
from app.engine.thesis import MOVE_Z, evaluate

from .conftest import login

NOW = datetime(2025, 6, 12, 6, 0)          # Thursday, mid-session IST


def flat_bars(n=60, price=100.0, wobble=0.01) -> list[Bar]:
    """Sixty alternating sessions — enough history for a real σ estimate.

    `wobble` maps to roughly 2× itself in σ_daily, so 0.01 ≈ a 2%/day blue chip
    and 0.03 ≈ a 6%/day small-cap. Keeping the fixture inside the range real
    NSE names actually occupy matters: an invented 16%/day stock would let any
    threshold pass and prove nothing.
    """
    out = []
    d = date(2025, 3, 3)
    for i in range(n):
        p = price * (1 + wobble * (1 if i % 2 else -1))
        out.append(Bar(d + timedelta(days=i), p, p * 1.005, p * 0.995, 100_000))
    return out


def make(**over):
    base = dict(
        thesis_id=1, symbol="TEST.NS", name="Test", text="cheap on cash flow", status="open",
        created_at=NOW - timedelta(days=10), anchored_at=NOW - timedelta(days=10),
        anchor_price=100.0, anchor_as_of=NOW - timedelta(days=10), horizon_days=90,
        snoozed_until=None, quote_price=100.0, quote_as_of=NOW, bars=flat_bars(),
        high_52w=140.0, low_52w=70.0, news_since_anchor=0, review_count=0,
        last_verdict=None, last_reviewed_at=None, now=NOW,
    )
    base.update(over)
    return evaluate(**base)


def test_quiet_thesis_is_not_a_prompt():
    v = make(quote_price=101.0)
    assert v.review_due is False and v.trigger is None


def test_statistically_rare_move_asks_you_to_re_read_it():
    v = make(quote_price=115.0)                       # 15% in 9 sessions, 2%/day stock
    assert v.trigger == "move" and v.review_due
    assert v.z is not None and abs(v.z) >= MOVE_Z
    assert "Up 15.0%" in v.trigger_text and "σ move" in v.trigger_text


def test_the_same_move_on_a_wilder_stock_is_not_a_trigger():
    """15% is a rare event for a blue chip and an ordinary fortnight for a
    6%/day small-cap. Volatility-normalising is the whole point."""
    v = make(quote_price=115.0, bars=flat_bars(wobble=0.03))
    assert v.trigger is None


def test_a_material_move_prompts_even_when_it_is_not_statistically_rare():
    """The failure mode this exists to prevent: because z divides by √n, a
    stock that bleeds a quarter of its value over a quarter scores well under
    2σ and would never prompt. Down 26% is a different position than the one
    you described, however unremarkable the statistics call it."""
    v = make(quote_price=74.0, bars=flat_bars(wobble=0.03),
             anchored_at=NOW - timedelta(days=120), anchor_as_of=NOW - timedelta(days=120),
             horizon_days=365)
    assert v.z is not None and abs(v.z) < MOVE_Z      # not "rare"
    assert v.trigger == "move" and "26.0% down on where you wrote it" in v.trigger_text


def test_material_threshold_still_respects_the_stock_s_own_range():
    """22% over seven months on a stock that swings 12% a day is a ripple, and
    the weak z floor exists exactly to catch this case."""
    v = make(quote_price=122.0, bars=flat_bars(wobble=0.06),
             anchored_at=NOW - timedelta(days=200), anchor_as_of=NOW - timedelta(days=200),
             horizon_days=365)
    assert v.trigger is None


def test_52_week_high_outranks_the_move_reason():
    v = make(quote_price=145.0)
    assert v.trigger == "range" and "52-week high" in v.trigger_text


def test_news_burst_triggers_below_the_move_threshold():
    v = make(quote_price=101.0, news_since_anchor=7)
    assert v.trigger == "news"


def test_horizon_expiry_is_the_last_resort():
    v = make(quote_price=100.5, anchored_at=NOW - timedelta(days=120), horizon_days=90)
    assert v.trigger == "time"


def test_snooze_silences_soft_triggers_but_not_a_52_week_breach():
    snoozed = NOW + timedelta(days=5)
    assert make(quote_price=112.0, snoozed_until=snoozed).trigger is None
    assert make(quote_price=145.0, snoozed_until=snoozed).trigger == "range"


def test_closed_theses_never_prompt():
    assert make(quote_price=145.0, status="closed").trigger is None


# ------------------------------------------------------------------ the API


def test_thesis_lifecycle(client):
    h = login(client)
    client.post("/api/watchlists/sample", headers=h)

    r = client.post("/api/thesis", headers=h, json={"symbol": "TCS", "text": "IT spend recovers in FY26", "horizon_days": 30})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["symbol"] == "TCS.NS" and t["anchor_price"] > 0 and t["review_count"] == 0

    # One open thesis per stock — otherwise the record means nothing.
    assert client.post("/api/thesis", headers=h, json={"symbol": "TCS", "text": "again"}).status_code == 409

    # It rides along on the briefing, attached to its stock.
    wl = client.get("/api/watchlists", headers=h).json()[0]
    b = client.get(f"/api/watchlists/{wl['id']}/briefing", headers=h).json()
    item = next(i for i in b["items"] if i["symbol"] == "TCS.NS")
    assert item["thesis"]["text"] == "IT spend recovers in FY26"
    assert b["summary"]["theses_open"] == 1
    assert "indices" in b

    r = client.post(f"/api/thesis/{t['id']}/review", headers=h, json={"verdict": "holds", "note": "deal wins intact"})
    assert r.status_code == 201, r.text
    assert r.json()["review_count"] == 1 and r.json()["last_verdict"] == "holds"

    page = client.get("/api/thesis", headers=h).json()
    assert page["record"]["holds"] == 1 and page["record"]["hold_rate"] == 1.0
    assert len(page["open"]) == 1 and page["closed"] == []

    # "Broken" closes it: the honest end state, not a thesis you keep failing.
    r = client.post(f"/api/thesis/{t['id']}/review", headers=h, json={"verdict": "broken", "note": "guidance cut"})
    assert r.json()["status"] == "closed"
    page = client.get("/api/thesis", headers=h).json()
    assert len(page["closed"]) == 1 and page["record"]["broken"] == 1
    assert len(page["closed"][0]["reviews"]) == 2

    # Which frees the symbol for a new one.
    assert client.post("/api/thesis", headers=h, json={"symbol": "TCS", "text": "restart"}).status_code == 201


def test_editing_the_reason_re_anchors_it(client):
    h = login(client)
    client.post("/api/watchlists/sample", headers=h)
    t = client.post("/api/thesis", headers=h, json={"symbol": "INFY", "text": "first reason"}).json()
    before = t["anchored_at"]
    r = client.patch(f"/api/thesis/{t['id']}", headers=h, json={"text": "different reason entirely"})
    assert r.status_code == 200
    assert r.json()["anchored_at"] >= before and r.json()["text"] == "different reason entirely"


def test_demo_rewind_uses_a_real_past_close_not_an_invented_one(client):
    """The demo control moves your anchor onto a close that is actually in the
    stored history. It must never fabricate a price to make the prompt fire."""
    h = login(client)
    client.post("/api/watchlists/sample", headers=h)
    t = client.post("/api/thesis", headers=h, json={"symbol": "SUZLON", "text": "order book", "horizon_days": 365}).json()
    r = client.post(f"/api/thesis/{t['id']}/demo/rewind?sessions=30", headers=h)
    assert r.status_code == 200, r.text
    anchor = r.json()["anchor_price"]

    bars = client.get("/api/compare?symbols=SUZLON&sessions=250", headers=h).json()["series"][0]
    # The anchor has to be a price this stock actually traded at, not a
    # synthesised one: it must sit inside the stock's own 52-week range.
    assert anchor > 0
    detail = client.get("/api/thesis", headers=h).json()
    got = next(x for x in detail["due"] + detail["open"] if x["id"] == t["id"])
    assert got["anchor_price"] == anchor
    # And the change shown is exactly (now / anchor - 1), not a stored guess.
    assert abs((got["price"] / anchor - 1) - got["change_pct"]) < 1e-9
    assert bars["last_price"] > 0


def test_snooze_defers_without_recording_a_review(client):
    """A dismissal and an answer must never look the same in the record."""
    h = login(client)
    client.post("/api/watchlists/sample", headers=h)
    t = client.post("/api/thesis", headers=h, json={"symbol": "HAL", "text": "capex cycle", "horizon_days": 30}).json()
    client.post(f"/api/thesis/{t['id']}/demo/rewind?sessions=60", headers=h)
    assert client.get("/api/thesis", headers=h).json()["due"][0]["id"] == t["id"]

    r = client.post(f"/api/thesis/{t['id']}/snooze?days=7", headers=h)
    assert r.status_code == 200 and r.json()["review_due"] is False
    page = client.get("/api/thesis", headers=h).json()
    assert page["due"] == [] and page["record"]["reviews"] == 0   # nothing recorded


def test_deleting_a_thesis_removes_it_and_its_reviews(client):
    h = login(client)
    client.post("/api/watchlists/sample", headers=h)
    t = client.post("/api/thesis", headers=h, json={"symbol": "INFY", "text": "gone soon"}).json()
    client.post(f"/api/thesis/{t['id']}/review", headers=h, json={"verdict": "holds", "note": "x"})
    assert client.delete(f"/api/thesis/{t['id']}", headers=h).status_code == 204
    assert client.get(f"/api/thesis/{t['id']}", headers=h).status_code == 404
    assert client.get("/api/thesis", headers=h).json()["record"]["reviews"] == 0


def test_rejects_verdicts_and_text_it_does_not_understand(client):
    h = login(client)
    client.post("/api/watchlists/sample", headers=h)
    t = client.post("/api/thesis", headers=h, json={"symbol": "ITC", "text": "demerger"}).json()
    assert client.post(f"/api/thesis/{t['id']}/review", headers=h, json={"verdict": "maybe"}).status_code == 422
    assert client.post("/api/thesis", headers=h, json={"symbol": "TCS", "text": "no"}).status_code == 422
    assert client.post("/api/thesis", headers=h, json={"symbol": "TCS", "text": "fine", "horizon_days": 5}).status_code == 422


def test_thesis_is_private_to_its_owner(client):
    h1 = login(client, email="a@example.com")
    h2 = login(client, email="b@example.com")
    client.post("/api/watchlists/sample", headers=h1)
    t = client.post("/api/thesis", headers=h1, json={"symbol": "ITC", "text": "mine"}).json()
    assert client.get(f"/api/thesis/{t['id']}", headers=h2).status_code == 404
    assert client.get("/api/thesis", headers=h2).json()["open"] == []
