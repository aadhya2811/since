from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import current_user
from ..config import settings
from ..db import get_db
from ..engine import baselines as bl
from ..engine.briefing import build_briefing
from ..market import calendar as cal
from ..market.store import get_bars_many
from ..market.universe import normalise
from ..models import PriceLevel, Quote, User
from ..util import utcnow
from .watchlists import get_owned

router = APIRouter(tags=["briefing"])


@router.get("/watchlists/{wl_id}/briefing", response_model=schemas.BriefingOut)
def briefing(wl_id: int, request: Request, x_visit_id: str | None = Header(default=None),
             user: User = Depends(current_user), db: Session = Depends(get_db)):
    wl = get_owned(db, user, wl_id)
    out = build_briefing(db, user, wl, visit_id=x_visit_id, now=utcnow(),
                         idle_minutes=settings.visit_idle_minutes, data_status=request.app.state.market.status())
    db.commit()  # baselines / visit bookkeeping
    return out


@router.post("/watchlists/{wl_id}/ack", status_code=204)
def acknowledge(wl_id: int, body: schemas.AckIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """'Seen it.' Resets the baseline for these symbols to the current quote."""
    wl = get_owned(db, user, wl_id)
    symbols = [normalise(s) for s in body.symbols] if body.symbols else [i.symbol for i in wl.items]
    now = utcnow()
    for q in db.scalars(select(Quote).where(Quote.symbol.in_(symbols))):
        bl.acknowledge(db, user.id, q.symbol, q, now)
    db.commit()


# ------------------------------------------------------------------ levels


@router.get("/levels", response_model=list[schemas.LevelOut])
def list_levels(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(PriceLevel).where(PriceLevel.user_id == user.id).order_by(PriceLevel.id)).all()


@router.post("/levels", response_model=schemas.LevelOut, status_code=201)
def create_level(body: schemas.LevelCreate, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lv = PriceLevel(user_id=user.id, symbol=normalise(body.symbol), price=body.price, direction=body.direction, note=body.note)
    db.add(lv)
    db.commit()
    db.refresh(lv)
    request.app.state.market.poke()
    return lv


@router.delete("/levels/{level_id}", status_code=204)
def delete_level(level_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lv = db.get(PriceLevel, level_id)
    if lv is None or lv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Level not found")
    db.delete(lv)
    db.commit()


# -------------------------------------------------------------------- demo


@router.post("/watchlists/{wl_id}/demo/rewind", response_model=dict)
def rewind(wl_id: int, body: schemas.RewindIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Time-travel: pretend the user last looked N sessions ago. Exists because
    the core feature is invisible to someone opening the app for the first
    time — they have no history to diff against."""
    wl = get_owned(db, user, wl_id)
    symbols = [i.symbol for i in wl.items]
    now = utcnow()
    bars = get_bars_many(db, symbols, limit=80)
    n = bl.rewind(db, user.id, bars, body.sessions, now, market_open=cal.market_state(now).is_open)
    db.commit()
    return {"rewound": n, "sessions": body.sessions}
