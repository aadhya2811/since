from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth, schemas
from ..config import settings
from ..db import get_db
from ..models import UserSession

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/request-code", response_model=schemas.RequestCodeOut)
async def request_code(body: schemas.RequestCodeIn, request: Request, db: Session = Depends(get_db)):
    mailer: auth.Mailer = request.app.state.mailer
    code, sent = await auth.request_code(db, body.email, mailer)
    # The code is shown in the app unless it actually reached an inbox. If SMTP
    # is configured but the send failed, showing it is what keeps sign-in
    # working — and the message says which happened, rather than claiming an
    # email is on its way when it isn't.
    show = settings.auth_dev_return_code or not sent.delivered
    if sent.delivered:
        message = f"Code sent to {body.email}. It expires in {max(1, settings.login_code_ttl_seconds // 60)} minutes."
    elif sent.error:
        message = "Couldn't reach the mail server, so here's your code directly."
    else:
        message = "Email isn't configured on this server, so here's your code."
    return schemas.RequestCodeOut(message=message, dev_code=code if show else None,
                                  delivery="email" if sent.delivered else "on-screen")


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
