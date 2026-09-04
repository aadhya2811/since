from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth, schemas
from ..config import settings
from ..db import get_db
from ..models import UserSession

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/request-code", response_model=schemas.RequestCodeOut)
def request_code(body: schemas.RequestCodeIn, db: Session = Depends(get_db)):
    code = auth.request_code(db, body.email)
    return schemas.RequestCodeOut(
        message="Check your email for a 6-digit code." if not settings.auth_dev_return_code
        else "Dev mode: code returned in response.",
        dev_code=code if settings.auth_dev_return_code else None,
    )


@router.post("/verify", response_model=schemas.TokenOut)
def verify(body: schemas.VerifyIn, db: Session = Depends(get_db)):
    token, user = auth.verify_code(db, body.email, body.code, body.device_label)
    return schemas.TokenOut(token=token, user=schemas.UserOut(id=user.id, email=user.email))


@router.get("/me", response_model=schemas.UserOut)
def me(ctx: auth.AuthContext = Depends(auth.current_auth)):
    return schemas.UserOut(id=ctx.user.id, email=ctx.user.email)


@router.get("/sessions", response_model=list[schemas.SessionOut])
def sessions(ctx: auth.AuthContext = Depends(auth.current_auth), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(UserSession).where(UserSession.user_id == ctx.user.id, UserSession.revoked.is_(False))
        .order_by(UserSession.last_seen_at.desc())
    ).all()
    return [schemas.SessionOut(id=s.id, device_label=s.device_label, created_at=s.created_at,
                               last_seen_at=s.last_seen_at, current=(s.id == ctx.session.id)) for s in rows]


@router.post("/logout", status_code=204)
def logout(ctx: auth.AuthContext = Depends(auth.current_auth), db: Session = Depends(get_db)):
    ctx.session.revoked = True
    db.commit()
