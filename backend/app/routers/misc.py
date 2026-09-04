from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import current_user
from ..db import get_db
from ..market import calendar as cal
from ..market.universe import search
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
        "tracked_symbols": db.scalar(select(func.count(func.distinct(WatchlistItem.symbol)))),
        "symbols_with_history": db.scalar(select(func.count()).select_from(SymbolMeta).where(SymbolMeta.bars_refreshed_at.is_not(None))),
        "newest_quote_fetched_at": newest,
    }
