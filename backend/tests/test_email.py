"""Login-code delivery: SMTP when configured, on-screen when not, and never
locking anyone out when the mail server misbehaves."""
import asyncio

import pytest

from app.config import Settings
from app.mailer import Mailer
from tests.conftest import login


def smtp_settings(**over) -> Settings:
    base = dict(smtp_host="smtp.example.com", smtp_port=587, smtp_user="u", smtp_password="p",
                smtp_from="since@example.com", smtp_from_name="Since")
    return Settings(**{**base, **over})


def test_unconfigured_mailer_falls_back_to_the_screen(caplog):
    m = Mailer(Settings(smtp_host=""))
    assert not m.configured and m.status()["mode"] == "console"
    r = asyncio.run(m.send_login_code("a@b.com", "123456"))
    assert not r.delivered and r.mode == "console" and r.error is None


def test_configured_mailer_builds_a_real_message_and_sends_it():
    m = Mailer(smtp_settings())
    sent = {}
    m._send = lambda msg: sent.update(msg=msg)          # stand in for smtplib
    r = asyncio.run(m.send_login_code("aadhya@example.com", "482913"))
    assert r.delivered and r.mode == "smtp"
    msg = sent["msg"]
    assert msg["To"] == "aadhya@example.com"
    assert "482913" in msg["Subject"]
    assert msg["From"] == "Since <since@example.com>"
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert "482913" in body and "expires" in body.lower()
    assert msg.get_body(preferencelist=("html",)) is not None   # multipart/alternative


def test_a_broken_mail_server_never_locks_anyone_out():
    m = Mailer(smtp_settings())

    def boom(_msg):
        raise OSError("connection refused")

    m._send = boom
    r = asyncio.run(m.send_login_code("a@b.com", "111111"))
    assert not r.delivered and r.error and "connection refused" in r.error
    assert m.status()["last_error"]


def test_api_shows_the_code_when_email_is_off_and_hides_it_once_delivered(client):
    r = client.post("/api/auth/request-code", json={"email": "x@y.com"})
    b = r.json()
    assert b["delivery"] == "on-screen" and b["dev_code"]           # zero-config path works
    assert "isn't configured" in b["message"]
    assert client.get("/api/health").json()["email"]["mode"] == "console"

    # Now pretend SMTP is live and delivery succeeds; the code stops being echoed.
    from app.mailer import SendResult
    mailer = client.app.state.mailer
    orig = mailer.send_login_code
    async def delivered(to, code):
        return SendResult(delivered=True, mode="smtp")
    mailer.send_login_code = delivered
    from app.config import settings
    settings.auth_dev_return_code = False
    try:
        b = client.post("/api/auth/request-code", json={"email": "x2@y.com"}).json()
        assert b["delivery"] == "email" and b["dev_code"] is None
        assert "Code sent to x2@y.com" in b["message"]
    finally:
        settings.auth_dev_return_code = True
        mailer.send_login_code = orig


def test_a_failed_send_still_returns_the_code_so_sign_in_works(client):
    from app.mailer import SendResult
    mailer = client.app.state.mailer
    orig = mailer.send_login_code
    async def failed(to, code):
        return SendResult(delivered=False, mode="smtp", error="TimeoutError: timed out")
    mailer.send_login_code = failed
    from app.config import settings
    settings.auth_dev_return_code = False          # even with echo off
    try:
        b = client.post("/api/auth/request-code", json={"email": "z@y.com"}).json()
        assert b["dev_code"], "a broken mail server must not make sign-in impossible"
        assert "Couldn't reach the mail server" in b["message"]
        v = client.post("/api/auth/verify", json={"email": "z@y.com", "code": b["dev_code"]})
        assert v.status_code == 200
    finally:
        settings.auth_dev_return_code = True
        mailer.send_login_code = orig


def test_requesting_codes_for_one_address_is_rate_limited(client):
    """The login box takes any address. Without a cap it is a free mailer."""
    for _ in range(6):
        assert client.post("/api/auth/request-code", json={"email": "victim@example.com"}).status_code == 200
    r = client.post("/api/auth/request-code", json={"email": "victim@example.com"})
    assert r.status_code == 429 and "Too many codes" in r.json()["detail"]
    # A different address is unaffected.
    assert client.post("/api/auth/request-code", json={"email": "someone@else.com"}).status_code == 200
