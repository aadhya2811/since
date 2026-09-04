"""Passwordless auth: email → 6-digit code → bearer token.

Why not passwords: the brief cares about state across devices, not about
credential storage. A magic code gives real multi-device identity in ~80
lines, with nothing to leak. In dev the code is returned by the API (and
logged) instead of emailed; `send_code` is the single seam where an email
provider plugs in.

Tokens are random 256-bit strings; only their SHA-256 is stored, so a DB leak
does not leak sessions.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import LoginCode, User, UserSession
from .util import random_code, random_token, sha256, utcnow

log = logging.getLogger(__name__)

MAX_CODE_ATTEMPTS = 5


def send_code(email: str, code: str) -> None:
    """Seam for an email provider. Dev: log it."""
    log.info("LOGIN CODE for %s: %s", email, code)


def request_code(db: Session, email: str) -> str:
    email = email.lower().strip()
    # Invalidate earlier unused codes so only the newest works.
    for old in db.scalars(select(LoginCode).where(LoginCode.email == email, LoginCode.used.is_(False))):
        old.used = True
    code = random_code()
    db.add(LoginCode(email=email, code_hash=sha256(code),
                     expires_at=utcnow() + timedelta(seconds=settings.login_code_ttl_seconds)))
    db.commit()
    send_code(email, code)
    return code


def verify_code(db: Session, email: str, code: str, device_label: str) -> tuple[str, User]:
    email = email.lower().strip()
    now = utcnow()
    lc = db.scalar(
        select(LoginCode).where(LoginCode.email == email, LoginCode.used.is_(False)).order_by(LoginCode.id.desc())
    )
    if lc is None or lc.expires_at < now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code expired or not found — request a new one.")
    if lc.attempts >= MAX_CODE_ATTEMPTS:
        lc.used = True
        db.commit()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts — request a new code.")
    if lc.code_hash != sha256(code.strip()):
        lc.attempts += 1
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Incorrect code.")
    lc.used = True

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email)
        db.add(user)
        db.flush()

    token = random_token()
    db.add(UserSession(token_hash=sha256(token), user_id=user.id, device_label=device_label[:120],
                       expires_at=now + timedelta(days=settings.session_ttl_days)))
    db.commit()
    return token, user


class AuthContext:
    def __init__(self, user: User, session: UserSession):
        self.user = user
        self.session = session


def current_auth(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> AuthContext:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == sha256(token)))
    now = utcnow()
    if sess is None or sess.revoked or sess.expires_at < now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session invalid or expired")
    user = db.get(User, sess.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    # Cheap write, but not on every request: once a minute per session.
    if (now - sess.last_seen_at) > timedelta(minutes=1):
        sess.last_seen_at = now
        db.commit()
    return AuthContext(user, sess)


def current_user(ctx: AuthContext = Depends(current_auth)) -> User:
    return ctx.user
