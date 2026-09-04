"""Watchlist CRUD with optimistic concurrency.

Every mutating request may carry `If-Match: <version>` — the version the
client last saw. The bump is a *conditional* UPDATE
(`... WHERE id=? AND version=?`), so two devices racing on the same list
cannot both win: one gets the new version, the other gets a 409 carrying the
current state and merges client-side. No lost updates, no locks held across
requests, and it works identically on SQLite and Postgres.

Clients that omit If-Match get last-writer-wins, which is the right default
for a single-device user.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import current_user
from ..db import get_db
from ..market.store import ensure_symbol
from ..market.universe import BY_SYMBOL, normalise
from ..models import Baseline, Quote, SymbolMeta, User, Watchlist, WatchlistItem
from ..util import utcnow
from ..engine import baselines as bl

router = APIRouter(prefix="/watchlists", tags=["watchlists"])

SAMPLE_SYMBOLS = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "TATAMOTORS.NS", "HAL.NS",
                  "INDUSINDBK.NS", "ITC.NS", "BAJFINANCE.NS", "ZOMATO.NS", "SUZLON.NS", "HINDUNILVR.NS"]


def to_out(db: Session, wl: Watchlist) -> schemas.WatchlistOut:
    names = {m.symbol: m.name for m in db.scalars(select(SymbolMeta).where(SymbolMeta.symbol.in_([i.symbol for i in wl.items])))} if wl.items else {}
    return schemas.WatchlistOut(
        id=wl.id, name=wl.name, version=wl.version, updated_at=wl.updated_at,
        items=[schemas.ItemOut(symbol=i.symbol, name=names.get(i.symbol) or (BY_SYMBOL[i.symbol].name if i.symbol in BY_SYMBOL else i.symbol),
                               position=i.position, added_at=i.added_at) for i in sorted(wl.items, key=lambda x: x.position)],
    )


def get_owned(db: Session, user: User, wl_id: int) -> Watchlist:
    wl = db.get(Watchlist, wl_id)
    if wl is None or wl.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Watchlist not found")
    return wl


def parse_if_match(if_match: str | None) -> int | None:
    if if_match is None or if_match == "*":
        return None
    try:
        return int(if_match.strip().strip('"'))
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "If-Match must be an integer version")


def bump_version(db: Session, wl: Watchlist, expected: int | None) -> None:
    """Conditional increment. Raises 409 if someone else moved the version."""
    stmt = update(Watchlist).where(Watchlist.id == wl.id).values(version=Watchlist.version + 1, updated_at=utcnow())
    if expected is not None:
        stmt = stmt.where(Watchlist.version == expected)
    res = db.execute(stmt)
    if res.rowcount == 0:
        db.rollback()
        fresh = db.get(Watchlist, wl.id)
        db.refresh(fresh)
        raise ConflictError(fresh)
    db.refresh(wl)


class ConflictError(Exception):
    def __init__(self, current: Watchlist):
        self.current = current


def conflict_response(db: Session, wl: Watchlist) -> JSONResponse:
    body = schemas.ConflictOut(detail="Watchlist was modified elsewhere. Reload and retry.", current=to_out(db, wl))
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=body.model_dump(mode="json"))


# ------------------------------------------------------------------ routes


@router.get("", response_model=list[schemas.WatchlistOut])
def list_watchlists(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Watchlist).where(Watchlist.user_id == user.id).order_by(Watchlist.id)).all()
    return [to_out(db, w) for w in rows]


@router.post("", response_model=schemas.WatchlistOut, status_code=201)
def create_watchlist(body: schemas.WatchlistCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    wl = Watchlist(user_id=user.id, name=body.name.strip())
    db.add(wl)
    db.commit()
    db.refresh(wl)
    return to_out(db, wl)


@router.post("/sample", response_model=schemas.WatchlistOut, status_code=201)
async def create_sample(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """A starter list so a first-time visitor sees the product working."""
    wl = Watchlist(user_id=user.id, name="Starter watchlist")
    db.add(wl)
    db.flush()
    for i, s in enumerate(SAMPLE_SYMBOLS):
        ensure_symbol(db, s)
        db.add(WatchlistItem(watchlist_id=wl.id, symbol=s, position=i))
    db.commit()
    db.refresh(wl)
    request.app.state.market.poke()
    # Warm the cache synchronously so the first briefing isn't empty.
    await request.app.state.market.refresh_quotes(SAMPLE_SYMBOLS)
    for s in SAMPLE_SYMBOLS:
        await request.app.state.market.refresh_bars(s)
        await request.app.state.market.refresh_news(s)
    return to_out(db, wl)


@router.patch("/{wl_id}", response_model=schemas.WatchlistOut)
def rename(wl_id: int, body: schemas.WatchlistRename, if_match: str | None = Header(default=None),
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    wl = get_owned(db, user, wl_id)
    try:
        bump_version(db, wl, parse_if_match(if_match))
    except ConflictError as e:
        return conflict_response(db, e.current)
    wl.name = body.name.strip()
    db.commit()
    db.refresh(wl)
    return to_out(db, wl)


@router.delete("/{wl_id}", status_code=204)
def delete(wl_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    wl = get_owned(db, user, wl_id)
    db.delete(wl)
    db.commit()
    return Response(status_code=204)


@router.post("/{wl_id}/items", response_model=schemas.WatchlistOut, status_code=201)
async def add_item(wl_id: int, body: schemas.ItemAdd, request: Request, if_match: str | None = Header(default=None),
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    wl = get_owned(db, user, wl_id)
    symbol = normalise(body.symbol)
    if any(i.symbol == symbol for i in wl.items):
        return to_out(db, wl)  # idempotent: adding twice is not an error
    market = request.app.state.market
    if symbol not in BY_SYMBOL and db.get(SymbolMeta, symbol) is None:
        # Unknown ticker: ask the provider before accepting it.
        ok = await market.ensure_symbol_data(symbol)
        if not ok:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown symbol {symbol}")
    try:
        bump_version(db, wl, parse_if_match(if_match))
    except ConflictError as e:
        return conflict_response(db, e.current)
    ensure_symbol(db, symbol)
    pos = (max((i.position for i in wl.items), default=-1) + 1)
    db.add(WatchlistItem(watchlist_id=wl.id, symbol=symbol, position=pos))
    db.commit()
    db.refresh(wl)
    # Fetch data now so the item is populated on the very next briefing, and
    # commit a baseline = "since you added it".
    if db.get(Quote, symbol) is None:
        await market.ensure_symbol_data(symbol)
    q = db.get(Quote, symbol)
    if q is not None and db.scalar(select(Baseline).where(Baseline.user_id == user.id, Baseline.symbol == symbol)) is None:
        bl.acknowledge(db, user.id, symbol, q, utcnow())
        db.commit()
    market.poke()
    return to_out(db, wl)


@router.delete("/{wl_id}/items/{symbol}", response_model=schemas.WatchlistOut)
def remove_item(wl_id: int, symbol: str, if_match: str | None = Header(default=None),
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    wl = get_owned(db, user, wl_id)
    symbol = normalise(symbol)
    item = next((i for i in wl.items if i.symbol == symbol), None)
    if item is None:
        return to_out(db, wl)  # idempotent
    try:
        bump_version(db, wl, parse_if_match(if_match))
    except ConflictError as e:
        return conflict_response(db, e.current)
    db.delete(item)
    db.commit()
    db.refresh(wl)
    return to_out(db, wl)


@router.put("/{wl_id}/items", response_model=schemas.WatchlistOut)
def reorder(wl_id: int, body: schemas.ItemsReorder, if_match: str | None = Header(default=None),
            user: User = Depends(current_user), db: Session = Depends(get_db)):
    wl = get_owned(db, user, wl_id)
    wanted = [normalise(s) for s in body.symbols]
    have = {i.symbol for i in wl.items}
    if set(wanted) != have or len(wanted) != len(have):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Reorder must contain exactly the current symbols")
    try:
        bump_version(db, wl, parse_if_match(if_match))
    except ConflictError as e:
        return conflict_response(db, e.current)
    order = {s: i for i, s in enumerate(wanted)}
    for it in wl.items:
        it.position = order[it.symbol]
    db.commit()
    db.refresh(wl)
    return to_out(db, wl)
