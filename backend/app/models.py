"""ORM models.

All timestamps are naive UTC (see util.utcnow). SQLite drops tzinfo anyway, and
one convention beats two.

Design notes
------------
* Market data (Quote, DailyBar, SymbolMeta) is keyed by symbol only — it is
  shared by every user who watches that symbol. 10,000 users watching RELIANCE
  cost one fetch, not 10,000.
* Per-user state (Baseline, PriceLevel, WatchlistItem) is small and cheap.
* Watchlist.version is the optimistic-concurrency token. Every write bumps it;
  clients send the version they last saw and get a 409 if it moved.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .util import utcnow


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Visit tracking: the baseline advances when a *visit* ends, not on every
    # refresh. See engine/baselines.py.
    current_visit_id: Mapped[str | None] = mapped_column(String(64))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)

    watchlists: Mapped[list[Watchlist]] = relationship(back_populates="user", cascade="all, delete-orphan")


class LoginCode(Base):
    __tablename__ = "login_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class UserSession(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_label: Mapped[str] = mapped_column(String(120), default="unknown device")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Watchlist(Base):
    __tablename__ = "watchlists"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="watchlists")
    items: Mapped[list[WatchlistItem]] = relationship(
        back_populates="watchlist", cascade="all, delete-orphan", order_by="WatchlistItem.position"
    )


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "symbol", name="uq_item_symbol"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    watchlist: Mapped[Watchlist] = relationship(back_populates="items")


class Pin(Base):
    """A symbol the user always wants on the top strip, across watchlists."""

    __tablename__ = "pins"
    __table_args__ = (UniqueConstraint("user_id", "symbol", name="uq_pin"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PriceLevel(Base):
    """A price the user cares about ("tell me if TCS goes under 3400")."""

    __tablename__ = "price_levels"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    price: Mapped[float] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(8))  # "above" | "below"
    note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime)


class Thesis(Base):
    """Why the user got interested in a stock, in their own words, timestamped.

    The rest of the app answers "what changed since you last looked?". This
    answers the question one level up: "is the reason you were interested still
    true?". It is the same diff, on a different clock — the baseline here is
    the price when you wrote the thesis (or when you last reviewed it), and the
    trigger for re-asking is a *material* change, not merely a new visit.

    One open thesis per user+symbol. Superseded ones stay for the history.
    """

    __tablename__ = "theses"
    __table_args__ = (Index("ix_thesis_user_symbol", "user_id", "symbol"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    horizon_days: Mapped[int] = mapped_column(Integer, default=90)  # ask me again by then regardless
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | closed
    # The anchor: price at the moment the thesis was written or last reviewed.
    # Reviews move it forward, so "since you last thought about this" stays true.
    anchor_price: Mapped[float | None] = mapped_column(Float)
    anchor_as_of: Mapped[datetime | None] = mapped_column(DateTime)
    anchored_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Set when the user answers a prompt; cleared when a fresh trigger fires.
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime)

    reviews: Mapped[list[ThesisReview]] = relationship(
        back_populates="thesis", cascade="all, delete-orphan", order_by="ThesisReview.created_at.desc()"
    )


class ThesisReview(Base):
    """One answer to "does this still hold?", with the price context at the
    time so the record is auditable after the fact."""

    __tablename__ = "thesis_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    thesis_id: Mapped[int] = mapped_column(ForeignKey("theses.id", ondelete="CASCADE"), index=True)
    verdict: Mapped[str] = mapped_column(String(16))     # holds | weakened | broken
    note: Mapped[str | None] = mapped_column(Text)
    trigger: Mapped[str] = mapped_column(String(16), default="manual")  # move | range | news | time | manual
    trigger_text: Mapped[str | None] = mapped_column(String(300))
    price_at_review: Mapped[float | None] = mapped_column(Float)
    change_pct: Mapped[float | None] = mapped_column(Float)   # vs the anchor being reviewed
    sessions: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    thesis: Mapped[Thesis] = relationship(back_populates="reviews")


class Baseline(Base):
    """What this user last *saw* for a symbol. The diff engine compares the
    current quote against this, not against yesterday's close.

    `committed_*` is the baseline in force. `pending_*` is what they saw most
    recently in the current visit; it becomes committed when the visit ends.
    """

    __tablename__ = "baselines"
    __table_args__ = (UniqueConstraint("user_id", "symbol", name="uq_baseline"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    committed_price: Mapped[float] = mapped_column(Float)
    committed_as_of: Mapped[datetime] = mapped_column(DateTime)   # market time of that price
    committed_seen_at: Mapped[datetime] = mapped_column(DateTime)  # when the user saw it
    pending_price: Mapped[float | None] = mapped_column(Float)
    pending_as_of: Mapped[datetime | None] = mapped_column(DateTime)
    pending_seen_at: Mapped[datetime | None] = mapped_column(DateTime)


# ---------------------------------------------------------------- market data


class SymbolMeta(Base):
    __tablename__ = "symbols"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    exchange: Mapped[str] = mapped_column(String(16), default="NSE")
    sector: Mapped[str | None] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    bars_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime)
    news_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # A ticker the feed does not know (delisted, renamed, typo). We stop
    # polling it and tell the user, instead of showing "waiting…" forever.
    unavailable: Mapped[bool] = mapped_column(Boolean, default=False)
    unavailable_reason: Mapped[str | None] = mapped_column(String(120))
    miss_count: Mapped[int] = mapped_column(Integer, default=0)


class Quote(Base):
    """Latest known quote per symbol. One row per symbol, overwritten in place
    but only ever forwards in market time (see market/store.py)."""

    __tablename__ = "quotes"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    price: Mapped[float] = mapped_column(Float)
    prev_close: Mapped[float | None] = mapped_column(Float)
    open: Mapped[float | None] = mapped_column(Float)
    day_high: Mapped[float | None] = mapped_column(Float)
    day_low: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(Integer)
    as_of: Mapped[datetime] = mapped_column(DateTime)      # exchange timestamp of the print
    fetched_at: Mapped[datetime] = mapped_column(DateTime)  # when we received it
    source: Mapped[str] = mapped_column(String(24))
    delay_minutes: Mapped[int | None] = mapped_column(Integer)  # vendor-declared lag


class Fundamental(Base):
    """Company figures that move quarterly, cached per symbol like any other
    market data — one fetch serves every user watching that stock.

    Every column is nullable and a NULL means "the vendor did not tell us",
    never zero. `source` and `fetched_at` travel with the row so the UI can
    show where a P/E came from and how old it is, which is the difference
    between a number you can check and a number you have to trust.
    """

    __tablename__ = "fundamentals"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    market_cap: Mapped[float | None] = mapped_column(Float)
    pe_trailing: Mapped[float | None] = mapped_column(Float)
    pe_forward: Mapped[float | None] = mapped_column(Float)
    price_to_book: Mapped[float | None] = mapped_column(Float)
    eps_trailing: Mapped[float | None] = mapped_column(Float)
    book_value: Mapped[float | None] = mapped_column(Float)
    roe: Mapped[float | None] = mapped_column(Float)
    dividend_yield: Mapped[float | None] = mapped_column(Float)
    debt_to_equity: Mapped[float | None] = mapped_column(Float)
    profit_margin: Mapped[float | None] = mapped_column(Float)
    revenue_growth: Mapped[float | None] = mapped_column(Float)
    beta: Mapped[float | None] = mapped_column(Float)
    as_of: Mapped[datetime | None] = mapped_column(DateTime)   # vendor's most-recent-quarter stamp
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    source: Mapped[str] = mapped_column(String(24), default="unknown")


class DailyBar(Base):
    __tablename__ = "daily_bars"
    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_bar"),
        Index("ix_bars_symbol_date", "symbol", "date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32))
    date: Mapped[date] = mapped_column(Date)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer)


class NewsItem(Base):
    __tablename__ = "news_items"
    __table_args__ = (
        UniqueConstraint("symbol", "guid", name="uq_news"),
        Index("ix_news_symbol_published", "symbol", "published_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32))
    guid: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(600))
    source: Mapped[str] = mapped_column(String(80))
    published_at: Mapped[datetime] = mapped_column(DateTime)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
