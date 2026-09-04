"""End-to-end API behaviour: auth, concurrency, visits/baselines, ack, rewind."""
from datetime import timedelta

from app.db import SessionLocal
from app.market.provider import QuoteData
from app.market.store import upsert_quote
from app.models import Quote, User
from app.util import utcnow
from tests.conftest import login


def setup_list(client, headers):
    r = client.post("/api/watchlists", json={"name": "Core"}, headers=headers)
    assert r.status_code == 201
    wl = r.json()
    for s in ["TCS.NS", "TATAMOTORS.NS"]:
        r = client.post(f"/api/watchlists/{wl['id']}/items", json={"symbol": s}, headers=headers)
        assert r.status_code == 201, r.text
    return client.get("/api/watchlists", headers=headers).json()[0]


def brief(client, headers, wl_id, visit="v1"):
    r = client.get(f"/api/watchlists/{wl_id}/briefing", headers={**headers, "X-Visit-Id": visit})
    assert r.status_code == 200, r.text
    return r.json()


def move_price(symbol, factor, minutes_ahead=5):
    """Simulate the market moving: write a newer quote directly to the store."""
    with SessionLocal() as db:
        q = db.get(Quote, symbol)
        upsert_quote(db, QuoteData(symbol=symbol, price=round(q.price * factor, 2), as_of=q.as_of + timedelta(minutes=minutes_ahead),
                                   prev_close=q.prev_close, volume=q.volume, source="simulated"))
        db.commit()


# --------------------------------------------------------------------- auth


def test_login_flow_and_bad_codes(client):
    r = client.post("/api/auth/request-code", json={"email": "A@Example.com"})
    code = r.json()["dev_code"]
    bad = client.post("/api/auth/verify", json={"email": "a@example.com", "code": "000000"})
    assert bad.status_code == 400
    ok = client.post("/api/auth/verify", json={"email": "a@example.com", "code": code, "device_label": "phone"})
    assert ok.status_code == 200
    reuse = client.post("/api/auth/verify", json={"email": "a@example.com", "code": code})
    assert reuse.status_code == 400  # single use
    assert client.get("/api/auth/me").status_code == 401
    h = {"Authorization": f"Bearer {ok.json()['token']}"}
    assert client.get("/api/auth/me", headers=h).json()["email"] == "a@example.com"


def test_two_devices_share_one_account(client):
    h1 = login(client, device="laptop")
    h2 = login(client, device="phone")
    wl = setup_list(client, h1)
    lists = client.get("/api/watchlists", headers=h2).json()
    assert [i["symbol"] for i in lists[0]["items"]] == ["TCS.NS", "TATAMOTORS.NS"]
    sessions = client.get("/api/auth/sessions", headers=h2).json()
    assert sorted(s["device_label"] for s in sessions) == ["laptop", "phone"]
    assert sum(s["current"] for s in sessions) == 1


# -------------------------------------------------------------- concurrency


def test_stale_version_gets_409_with_current_state(client):
    h = login(client)
    wl = setup_list(client, h)
    v = wl["version"]
    r1 = client.post(f"/api/watchlists/{wl['id']}/items", json={"symbol": "INFY"}, headers={**h, "If-Match": str(v)})
    assert r1.status_code == 201 and r1.json()["version"] == v + 1
    r2 = client.delete(f"/api/watchlists/{wl['id']}/items/TCS.NS", headers={**h, "If-Match": str(v)})
    assert r2.status_code == 409
    body = r2.json()
    assert body["current"]["version"] == v + 1
    assert "INFY.NS" in [i["symbol"] for i in body["current"]["items"]]
    # Retry with the fresh version succeeds.
    r3 = client.delete(f"/api/watchlists/{wl['id']}/items/TCS.NS", headers={**h, "If-Match": str(v + 1)})
    assert r3.status_code == 200 and r3.json()["version"] == v + 2


def test_add_and_remove_are_idempotent(client):
    h = login(client)
    wl = setup_list(client, h)
    r = client.post(f"/api/watchlists/{wl['id']}/items", json={"symbol": "tcs"}, headers=h)
    assert r.status_code == 201 and len(r.json()["items"]) == 2
    r = client.delete(f"/api/watchlists/{wl['id']}/items/NOTTHERE.NS", headers=h)
    assert r.status_code == 200 and len(r.json()["items"]) == 2


def test_cannot_touch_someone_elses_watchlist(client):
    h1, h2 = login(client, email="one@x.com"), login(client, email="two@x.com")
    wl = setup_list(client, h1)
    assert client.get(f"/api/watchlists/{wl['id']}/briefing", headers=h2).status_code == 404
    assert client.delete(f"/api/watchlists/{wl['id']}", headers=h2).status_code == 404


# ---------------------------------------------------------- since-you-looked


def test_baseline_advances_on_new_visit_not_on_refresh(client):
    h = login(client)
    wl = setup_list(client, h)
    b0 = brief(client, h, wl["id"], visit="v1")
    tcs = next(i for i in b0["items"] if i["symbol"] == "TCS.NS")
    p0 = tcs["quote"]["price"]
    assert abs(tcs["since"]["change_pct"]) < 1e-9  # just added: baseline == now

    move_price("TCS.NS", 1.05)
    b1 = brief(client, h, wl["id"], visit="v1")   # same visit: diff shows +5%
    tcs1 = next(i for i in b1["items"] if i["symbol"] == "TCS.NS")
    assert tcs1["since"]["baseline_price"] == p0
    assert 0.049 < tcs1["since"]["change_pct"] < 0.051
    assert tcs1["tier"] == "attention"
    assert any("Up 5.0%" in r["text"] for r in tcs1["reasons"])

    b2 = brief(client, h, wl["id"], visit="v1")   # refresh within the visit: baseline unchanged
    assert next(i for i in b2["items"] if i["symbol"] == "TCS.NS")["since"]["baseline_price"] == p0

    b3 = brief(client, h, wl["id"], visit="v2")   # they left and came back: baseline is what they last saw
    assert b3["new_visit"]
    tcs3 = next(i for i in b3["items"] if i["symbol"] == "TCS.NS")
    assert abs(tcs3["since"]["baseline_price"] - round(p0 * 1.05, 2)) < 0.01
    assert abs(tcs3["since"]["change_pct"]) < 1e-9


def test_idle_timeout_starts_a_new_visit_even_with_same_visit_id(client):
    h = login(client)
    wl = setup_list(client, h)
    brief(client, h, wl["id"], visit="v1")
    move_price("TCS.NS", 1.03)
    brief(client, h, wl["id"], visit="v1")
    with SessionLocal() as db:
        u = db.query(User).first()
        u.last_seen_at = utcnow() - timedelta(minutes=45)
        db.commit()
    b = brief(client, h, wl["id"], visit="v1")
    assert b["new_visit"]
    assert abs(next(i for i in b["items"] if i["symbol"] == "TCS.NS")["since"]["change_pct"]) < 1e-9


def test_acknowledge_resets_baseline_immediately(client):
    h = login(client)
    wl = setup_list(client, h)
    brief(client, h, wl["id"])
    move_price("TCS.NS", 0.94)
    b = brief(client, h, wl["id"])
    assert next(i for i in b["items"] if i["symbol"] == "TCS.NS")["tier"] == "attention"
    assert client.post(f"/api/watchlists/{wl['id']}/ack", json={"symbols": ["TCS.NS"]}, headers=h).status_code == 204
    b = brief(client, h, wl["id"])
    tcs = next(i for i in b["items"] if i["symbol"] == "TCS.NS")
    assert abs(tcs["since"]["change_pct"]) < 1e-9 and tcs["tier"] == "quiet"


def test_rewind_sets_baseline_to_a_past_close(client):
    h = login(client)
    wl = setup_list(client, h)
    r = client.post(f"/api/watchlists/{wl['id']}/demo/rewind", json={"sessions": 3}, headers=h)
    assert r.json()["rewound"] == 2
    b = brief(client, h, wl["id"])
    tm = next(i for i in b["items"] if i["symbol"] == "TATAMOTORS.NS")
    assert tm["since"]["sessions"] == 3
    assert tm["since"]["change_pct"] < -0.03      # the scripted -5.8% drop is inside the window
    assert tm["tier"] in ("attention", "notable")
    assert b["summary"]["headline"] != "Nothing has changed since you last looked."


def test_level_crossing_surfaces_in_briefing(client):
    h = login(client)
    wl = setup_list(client, h)
    b = brief(client, h, wl["id"])
    price = next(i for i in b["items"] if i["symbol"] == "TCS.NS")["quote"]["price"]
    r = client.post("/api/levels", json={"symbol": "TCS.NS", "price": round(price * 0.98, 2), "direction": "below",
                                         "note": "add here"}, headers=h)
    assert r.status_code == 201
    move_price("TCS.NS", 0.97)
    b = brief(client, h, wl["id"])
    tcs = next(i for i in b["items"] if i["symbol"] == "TCS.NS")
    assert tcs["levels_crossed"] == [r.json()["id"]]
    assert any("Fell through" in x["text"] and "add here" in x["text"] for x in tcs["reasons"])
    assert tcs["tier"] == "attention"


def test_briefing_survives_provider_outage_with_stale_data(client):
    h = login(client)
    wl = setup_list(client, h)
    client.market.provider.chain[0].fail = True
    import asyncio
    asyncio.get_event_loop().run_until_complete(client.market.refresh_quotes(["TCS.NS"]))
    b = brief(client, h, wl["id"])
    assert b["summary"]["missing"] == 0                 # old quotes still served
    assert client.get("/api/health").json()["data"]["providers"][0]["failures"] >= 1


def test_news_is_diffed_against_baseline_and_attached_to_moves(client):
    h = login(client)
    r = client.post("/api/watchlists/sample", headers=h)
    wl = r.json()
    # Rewind 3 sessions: the scripted Tata Motors drop *and* its headlines fall inside the window.
    client.post(f"/api/watchlists/{wl['id']}/demo/rewind", json={"sessions": 3}, headers=h)
    b = brief(client, h, wl["id"])
    tm = next(i for i in b["items"] if i["symbol"] == "TATAMOTORS.NS")
    assert tm["news"]["new_count"] >= 1
    assert any(r["kind"] == "news" and "JLR" in r["text"] for r in tm["reasons"])
    # Acknowledge → headlines are no longer "new".
    client.post(f"/api/watchlists/{wl['id']}/ack", json={"symbols": ["TATAMOTORS.NS"]}, headers=h)
    b = brief(client, h, wl["id"])
    tm = next(i for i in b["items"] if i["symbol"] == "TATAMOTORS.NS")
    assert tm["news"]["new_count"] == 0
    assert len(tm["news"]["items"]) >= 1  # still listed as context, just not flagged
