"""Email delivery for login codes.

Design: email is a *capability*, not a requirement. If SMTP is configured the
code is emailed; if it isn't, the code is shown on screen. That ordering is
deliberate —

  * anyone who clones this repo can sign in immediately, with no credentials
    to obtain and nothing to configure;
  * a deployment that *has* credentials sends a real email;
  * and a misconfigured or temporarily-down mail server degrades to the
    on-screen code rather than locking every user out of the product.

An auth system whose only path to a session runs through a third party you
don't control is a single point of failure with a support burden attached.
This one has a fallback that is always available and always honest about
which mode it is in (`/api/health` reports it).

Sending happens on a worker thread: smtplib is blocking, and a slow mail
server must not hold the request open.
"""
from __future__ import annotations

import asyncio
import logging
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from .config import Settings

log = logging.getLogger(__name__)

_ADDR = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class SendResult:
    delivered: bool
    mode: str            # "smtp" | "console"
    error: str | None = None


class Mailer:
    """Sends login codes. Configured entirely by env vars (SINCE_SMTP_*)."""

    def __init__(self, settings: Settings):
        self.s = settings
        self.last_error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.s.smtp_host and self.s.smtp_from)

    # ------------------------------------------------------------- public
    async def send_login_code(self, to: str, code: str) -> SendResult:
        if not self.configured:
            log.info("LOGIN CODE for %s: %s  (no SMTP configured — shown in the app)", to, code)
            return SendResult(delivered=False, mode="console")
        if not _ADDR.match(to):
            return SendResult(delivered=False, mode="smtp", error="invalid address")
        msg = self._build(to, code)
        try:
            # smtplib blocks; keep it off the event loop.
            await asyncio.wait_for(asyncio.to_thread(self._send, msg), timeout=self.s.smtp_timeout_seconds + 5)
            self.last_error = None
            log.info("login code emailed to %s", to)
            return SendResult(delivered=True, mode="smtp")
        except Exception as e:  # noqa: BLE001 — never let mail trouble break sign-in
            self.last_error = f"{type(e).__name__}: {e}"[:200]
            log.warning("SMTP send failed for %s (%s) — falling back to the on-screen code", to, self.last_error)
            log.info("LOGIN CODE for %s: %s", to, code)
            return SendResult(delivered=False, mode="smtp", error=self.last_error)

    def status(self) -> dict:
        return {
            "configured": self.configured,
            "mode": "smtp" if self.configured else "console",
            "host": self.s.smtp_host or None,
            "from": self.s.smtp_from or None,
            "last_error": self.last_error,
        }

    # ------------------------------------------------------------ internals
    def _build(self, to: str, code: str) -> EmailMessage:
        m = EmailMessage()
        m["Subject"] = f"{code} is your Since sign-in code"
        m["From"] = formataddr((self.s.smtp_from_name, self.s.smtp_from))
        m["To"] = to
        m["Date"] = formatdate(localtime=True)
        m["Message-ID"] = make_msgid(domain=self.s.smtp_from.split("@")[-1])
        # Mail clients that surface a one-time code in the notification look for this.
        m["X-Entity-Ref-ID"] = code
        mins = max(1, self.s.login_code_ttl_seconds // 60)
        m.set_content(
            f"Your Since sign-in code is {code}\n\n"
            f"It expires in {mins} minutes and can be used once.\n\n"
            "If you didn't try to sign in, you can ignore this email — "
            "nobody can get into your account with just your address.\n"
        )
        m.add_alternative(_HTML.format(code=code, mins=mins), subtype="html")
        return m

    def _send(self, msg: EmailMessage) -> None:
        host, port = self.s.smtp_host, self.s.smtp_port
        ctx = ssl.create_default_context()
        if self.s.smtp_ssl:                      # implicit TLS, usually port 465
            server = smtplib.SMTP_SSL(host, port, timeout=self.s.smtp_timeout_seconds, context=ctx)
        else:
            server = smtplib.SMTP(host, port, timeout=self.s.smtp_timeout_seconds)
        with server:
            server.ehlo()
            if self.s.smtp_starttls and not self.s.smtp_ssl:   # STARTTLS, usually port 587
                server.starttls(context=ctx)
                server.ehlo()
            if self.s.smtp_user:
                server.login(self.s.smtp_user, self.s.smtp_password or "")
            server.send_message(msg)


_HTML = """\
<!doctype html>
<html><body style="margin:0;padding:0;background:#07080f;">
  <div style="max-width:440px;margin:0 auto;padding:40px 24px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;color:#eef0ff;">
    <div style="font-size:22px;font-weight:800;letter-spacing:-.02em;">Since<span style="color:#a855f7;">.</span></div>
    <div style="color:#a4a9c8;font-size:13px;margin-top:2px;">what changed since you last looked</div>
    <div style="margin:28px 0 8px;font-size:15px;color:#a4a9c8;">Your sign-in code:</div>
    <div style="font-family:ui-monospace,Menlo,Consolas,monospace;font-size:34px;font-weight:700;letter-spacing:.32em;
                background:rgba(99,102,241,.14);border:1px solid rgba(139,92,246,.45);border-radius:12px;
                padding:18px 12px;text-align:center;color:#c4b5fd;">{code}</div>
    <div style="margin-top:18px;font-size:14px;color:#a4a9c8;line-height:1.5;">
      Expires in {mins} minutes, and works once.
    </div>
    <div style="margin-top:22px;padding-top:18px;border-top:1px solid rgba(255,255,255,.08);font-size:12.5px;color:#6b7194;line-height:1.5;">
      Didn't try to sign in? Ignore this — knowing your email address isn't enough to get into your account.
    </div>
  </div>
</body></html>
"""
