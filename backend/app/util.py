from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC now. The whole codebase stores naive UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def random_code(digits: int = 6) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(digits))
