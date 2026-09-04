from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

# ------------------------------------------------------------------- auth


class RequestCodeIn(BaseModel):
    email: EmailStr


class RequestCodeOut(BaseModel):
    ok: bool = True
    message: str
    dev_code: str | None = None  # only populated when SINCE_AUTH_DEV_RETURN_CODE=true


class VerifyIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=8)
    device_label: str = Field(default="unknown device", max_length=120)


class TokenOut(BaseModel):
    token: str
    user: UserOut


class UserOut(BaseModel):
    id: int
    email: str


class SessionOut(BaseModel):
    id: int
    device_label: str
    created_at: datetime
    last_seen_at: datetime
    current: bool


# ------------------------------------------------------------ watchlists


class WatchlistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class WatchlistRename(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ItemAdd(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)


class ItemsReorder(BaseModel):
    symbols: list[str]


class ItemOut(BaseModel):
    symbol: str
    name: str
    position: int
    added_at: datetime


class WatchlistOut(BaseModel):
    id: int
    name: str
    version: int
    updated_at: datetime
    items: list[ItemOut]


class ConflictOut(BaseModel):
    detail: str
    current: WatchlistOut


# ---------------------------------------------------------------- levels


class LevelCreate(BaseModel):
    symbol: str
    price: float = Field(gt=0)
    direction: str = Field(pattern="^(above|below)$")
    note: str | None = Field(default=None, max_length=200)


class LevelOut(BaseModel):
    id: int
    symbol: str
    price: float
    direction: str
    note: str | None
    created_at: datetime


# -------------------------------------------------------------- briefing


class Freshness(BaseModel):
    status: str        # live | delayed | closed | stale | missing
    label: str
    as_of: datetime | None
    fetched_at: datetime | None
    source: str | None
    delay_minutes: int | None = None


class QuoteOut(BaseModel):
    price: float
    prev_close: float | None
    open: float | None
    day_high: float | None
    day_low: float | None
    volume: int | None
    day_change_pct: float | None
    freshness: Freshness


class UnusualOut(BaseModel):
    """Plain-language version of the z-score, for people who don't speak σ."""
    label: str          # "Unchanged" | "Ordinary" | "Notable" | "Rare" | "Extreme"
    text: str           # "Moved 0.1% — a normal day for this stock is about ±0.9%."
    z: float | None
    typical_move_pct: float          # σ_daily, as a fraction
    typical_window_pct: float | None # σ over the elapsed sessions, as a fraction


class SinceOut(BaseModel):
    baseline_price: float
    baseline_as_of: datetime
    seen_at: datetime
    seen_label: str
    change_abs: float
    change_pct: float
    sessions: int
    z: float | None
    unusual: UnusualOut
    market_change_pct: float | None = None
    market_share: float | None = None


class ReasonOut(BaseModel):
    kind: str
    severity: str
    text: str


class NewsOut(BaseModel):
    title: str
    url: str
    source: str
    published_at: datetime
    is_new: bool          # published after the user's baseline


class NewsSummary(BaseModel):
    new_count: int
    items: list[NewsOut]


class BriefingItem(BaseModel):
    symbol: str
    pinned: bool = False
    watchlist_id: int | None = None
    name: str
    sector: str | None
    tier: str
    score: float
    quote: QuoteOut | None
    since: SinceOut | None
    reasons: list[ReasonOut]
    volume_ratio: float | None
    range_position_52w: float | None
    high_52w: float | None
    low_52w: float | None
    sigma_daily: float | None
    streak: int
    sparkline: list[float]
    levels: list[LevelOut]
    levels_crossed: list[int]
    news: NewsSummary


class MarketOut(BaseModel):
    is_open: bool
    phase: str
    session_date: str
    last_close: datetime
    next_open: datetime


class DataStatus(BaseModel):
    active_provider: str
    degraded: bool
    note: str | None


class BriefingSummary(BaseModel):
    attention: int
    notable: int
    quiet: int
    missing: int
    headline: str


class BriefingOut(BaseModel):
    watchlist_id: int
    watchlist_version: int
    generated_at: datetime
    new_visit: bool
    first_visit: bool      # no baselines existed before this request: nothing to diff yet
    market: MarketOut
    data: DataStatus
    summary: BriefingSummary
    items: list[BriefingItem]


class PinIn(BaseModel):
    symbol: str


class PinOut(BaseModel):
    id: int
    symbol: str
    position: int


class BoardOut(BaseModel):
    generated_at: datetime
    items: list[BriefingItem]


class AckIn(BaseModel):
    symbols: list[str] | None = None  # None = everything on this watchlist


class RewindIn(BaseModel):
    sessions: int = Field(ge=0, le=60)


class SymbolOut(BaseModel):
    symbol: str
    name: str
    sector: str | None


# ------------------------------------------------------------ market page


class IndexOut(BaseModel):
    symbol: str
    name: str
    price: float | None
    ret_1d: float | None
    ret_5d: float | None
    ret_20d: float | None
    sparkline: list[float]


class SectorOut(BaseModel):
    sector: str
    n: int
    ret_1d: float | None
    ret_5d: float | None
    ret_20d: float | None
    members: list[str]


class MoverOut(BaseModel):
    symbol: str
    name: str
    sector: str | None
    price: float | None
    ret_1d: float | None
    ret_5d: float | None
    ret_20d: float | None
    z_5d: float | None
    sparkline: list[float]


class MarketPageOut(BaseModel):
    generated_at: datetime
    session_date: str
    is_open: bool
    universe_size: int
    scanned: int
    indices: list[IndexOut]
    sectors: list[SectorOut]
    gainers_5d: list[MoverOut]
    losers_5d: list[MoverOut]
    unusual_5d: list[MoverOut]
    highs_52w: list[MoverOut]
    lows_52w: list[MoverOut]


# ---------------------------------------------------------------- compare


class CompareSeries(BaseModel):
    symbol: str
    name: str
    rebased: list[float]          # first point = 100
    last_price: float
    return_pct: float
    volatility_annual: float
    max_drawdown: float
    range_position_52w: float | None
    avg_volume_20d: float | None
    best_day: float | None
    worst_day: float | None


class CompareOut(BaseModel):
    generated_at: datetime
    sessions: int
    dates: list[str]
    series: list[CompareSeries]
    correlation: list[list[float | None]]


# -------------------------------------------------------------- news feed


class NewsFeedItem(BaseModel):
    symbol: str
    name: str
    title: str
    url: str
    source: str
    published_at: datetime
    is_new: bool


class NewsFeedOut(BaseModel):
    generated_at: datetime
    symbols: list[str]
    items: list[NewsFeedItem]
