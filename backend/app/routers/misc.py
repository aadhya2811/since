from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import current_user
from ..db import get_db
from ..market import calendar as cal
from ..engine.analytics import build_compare, build_market, build_news_feed
from ..market.universe import normalise, search
from ..models import Quote, SymbolMeta, User, WatchlistItem
from ..util import utcnow

router = APIRouter(tags=["misc"])


@router.get("/symbols/search", response_model=list[schemas.SymbolOut])
def symbol_search(q: str = "", user: User = Depends(current_user)):
    return [schemas.SymbolOut(symbol=s.symbol, name=s.name, sector=s.sector) for s in search(q)]


@router.get("/health")
def health(request: Request, db: Session = Depends(get_db)):
    now = utcnow()
    st = cal.market_state(now)
    newest = db.scalar(select(func.max(Quote.fetched_at)))
    return {
        "ok": True,
        "time": now,
        "market": {"is_open": st.is_open, "phase": st.phase, "session_date": st.session_date.isoformat()},
        "data": request.app.state.market.status(),
        "email": request.app.state.mailer.status(),
        "tracked_symbols": db.scalar(select(func.count(func.distinct(WatchlistItem.symbol)))),
        "symbols_with_history": db.scalar(select(func.count()).select_from(SymbolMeta).where(SymbolMeta.bars_refreshed_at.is_not(None))),
        "newest_quote_fetched_at": newest,
    }


# ------------------------------------------------------------ pages' data


@router.get("/market", response_model=schemas.MarketPageOut)
def market_page(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """What's moving across the universe: indices, sectors, movers, 52w breaches.
    Information, not advice."""
    return build_market(db, utcnow())


@router.get("/compare", response_model=schemas.CompareOut)
async def compare(request: Request, symbols: str = Query(..., description="comma-separated"), sessions: int = Query(60, ge=5, le=250),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    syms = [normalise(s) for s in symbols.split(",") if s.strip()][:6]
    if len(syms) < 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Give at least one symbol")
    # Symbols not yet tracked (typed into the picker) get fetched on demand.
    market = request.app.state.market
    for s in syms:
        if not db.get(SymbolMeta, s) or db.get(SymbolMeta, s).bars_refreshed_at is None:
            await market.ensure_symbol_data(s)
    db.expire_all()
    return build_compare(db, syms, sessions, utcnow())


@router.get("/news", response_model=schemas.NewsFeedOut)
def news_feed(days: int = Query(7, ge=1, le=30),
              scope: str = Query("all", pattern="^(all|following|market)$"),
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    return build_news_feed(db, user.id, utcnow(), days=days, scope=scope)
