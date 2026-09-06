"""Analyst memory endpoints.

Writing a thesis is cheap; the value is entirely in being asked about it later,
at a moment you did not choose. So the interesting endpoint here is not POST
/thesis — it is GET /thesis, which decides *which* of your reasons the market
has earned the right to interrupt you about. That logic lives in
engine/thesis.py; this file is transport.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import schemas
from ..auth import current_user
from ..db import get_db
from ..engine import thesis as th
from ..market import calendar as cal
from ..market.store import ensure_symbol
from ..market.universe import normalise
from ..models import Quote, SymbolMeta, Thesis, User
from ..util import utcnow

router = APIRouter(prefix="/thesis", tags=["thesis"])


def owned(db: Session, user: User, tid: int) -> Thesis:
    t = db.get(Thesis, tid)
    if t is None or t.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thesis not found")
    return t


def view_of(db: Session, user: User, t: Thesis, now) -> th.ThesisView:
    """Re-evaluate one thesis. Cheap enough not to bother optimising, and it
    keeps the review record honest — the trigger stored alongside a verdict is
    the trigger that was actually showing when the user answered."""
    views = th.load_views(db, user.id, now, symbols=[t.symbol], include_closed=True)
    v = next((x for x in views if x.id == t.id), None)
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thesis not found")
    return v


@router.get("", response_model=schemas.ThesisPageOut)
def list_theses(user: User = Depends(current_user), db: Session = Depends(get_db)):
    now = utcnow()
    views = th.load_views(db, user.id, now, include_closed=True)
    rows = {t.id: t for t in db.scalars(
        select(Thesis).where(Thesis.user_id == user.id).options(selectinload(Thesis.reviews))
    )}
    outs = [th.to_out(v, rows[v.id].reviews if v.id in rows else []) for v in views]
    return schemas.ThesisPageOut(
        generated_at=now,
        record=schemas.ThesisRecord(**th.history(db, user.id)),
        due=[o for o in outs if o.review_due],
        open=[o for o in outs if o.status == "open" and not o.review_due],
        closed=[o for o in outs if o.status == "closed"],
    )


@router.post("", response_model=schemas.ThesisOut, status_code=201)
async def create(body: schemas.ThesisCreate, request: Request,
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    symbol = normalise(body.symbol)
    if th.open_thesis(db, user.id, symbol) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "You already have an open thesis for this stock. Edit it, or review it first.")
    if db.get(SymbolMeta, symbol) is None or db.get(Quote, symbol) is None:
        await request.app.state.market.ensure_symbol_data(symbol)
    ensure_symbol(db, symbol)
    q = db.get(Quote, symbol)
    now = utcnow()
    t = Thesis(user_id=user.id, symbol=symbol, text=body.text.strip(), horizon_days=body.horizon_days,
               anchor_price=q.price if q else None, anchor_as_of=q.as_of if q else None,
               anchored_at=now, created_at=now)
    db.add(t)
    db.commit()
    db.refresh(t)
    return th.to_out(view_of(db, user, t, utcnow()), [])


@router.get("/{tid}", response_model=schemas.ThesisOut)
def get_one(tid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, user, tid)
    return th.to_out(view_of(db, user, t, utcnow()), t.reviews)


@router.patch("/{tid}", response_model=schemas.ThesisOut)
def edit(tid: int, body: schemas.ThesisPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Rewriting the reason is allowed and normal — theses evolve. What is not
    allowed is rewriting it *and* keeping the old anchor, which would let you
    quietly move the goalposts: an edited thesis re-anchors to today."""
    t = owned(db, user, tid)
    now = utcnow()
    if body.text is not None and body.text.strip() != t.text:
        t.text = body.text.strip()
        q = db.get(Quote, t.symbol)
        if q is not None:
            t.anchor_price, t.anchor_as_of = q.price, q.as_of
        t.anchored_at = now
        t.snoozed_until = None
    if body.horizon_days is not None:
        t.horizon_days = body.horizon_days
    db.commit()
    db.refresh(t)
    return th.to_out(view_of(db, user, t, now), t.reviews)


@router.delete("/{tid}", status_code=204)
def remove(tid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(owned(db, user, tid))
    db.commit()
    return Response(status_code=204)


@router.post("/{tid}/review", response_model=schemas.ThesisOut, status_code=201)
def review(tid: int, body: schemas.ReviewCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, user, tid)
    now = utcnow()
    v = view_of(db, user, t, now)
    th.record_review(db, t, verdict=body.verdict, note=body.note, view=v, now=now, quote=db.get(Quote, t.symbol))
    db.commit()
    db.refresh(t)
    return th.to_out(view_of(db, user, t, now), t.reviews)


@router.post("/{tid}/demo/rewind", response_model=schemas.ThesisOut)
def demo_rewind(tid: int, sessions: int = 30, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Pretend you wrote this reason N sessions ago.

    A thesis is a three-month instrument; nobody evaluating this app has three
    months. So the anchor is moved back to a *real* close from the stored
    history — not a fabricated price — and the prompt then fires or doesn't
    fire on its own merits, exactly as it would have. This is the same
    affordance the briefing's "Try it" strip uses, for the same reason, and it
    is a demo control: it changes your anchor, nothing about the market.
    """
    from ..market.store import get_bars

    t = owned(db, user, tid)
    bars = get_bars(db, t.symbol, limit=300)
    if len(bars) < 2:
        raise HTTPException(status.HTTP_409_CONFLICT, "No price history stored for this symbol yet")
    b = bars[max(0, len(bars) - 1 - max(1, sessions))]
    now = utcnow()
    t.anchor_price = b.close
    t.anchor_as_of = cal._utc_naive(b.date, cal.CLOSE)
    t.anchored_at = t.anchor_as_of
    t.created_at = min(t.created_at, t.anchor_as_of)
    t.snoozed_until = None
    db.commit()
    db.refresh(t)
    return th.to_out(view_of(db, user, t, now), t.reviews)


@router.post("/{tid}/snooze", response_model=schemas.ThesisOut)
def snooze(tid: int, days: int = 7, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """'Not now.' Silences this prompt for a week without pretending you
    answered it — a dismissed prompt and a reviewed thesis must not look the
    same in the record. A 52-week breach still gets through."""
    from datetime import timedelta

    t = owned(db, user, tid)
    now = utcnow()
    t.snoozed_until = now + timedelta(days=max(1, min(days, 60)))
    db.commit()
    db.refresh(t)
    return th.to_out(view_of(db, user, t, now), t.reviews)
