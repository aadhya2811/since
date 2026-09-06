"""Market data provider interface.

Everything above this layer speaks in `QuoteData` and `BarData` and never
knows which vendor produced them. That is what lets us swap Yahoo for a
simulated feed in tests, and fail over between them at runtime.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime


class ProviderError(Exception):
    """Any upstream failure: network, HTTP 4xx/5xx, malformed payload."""


class SymbolNotFound(ProviderError):
    pass


@dataclass(frozen=True)
class QuoteData:
    symbol: str
    price: float
    as_of: datetime            # exchange time of the print, UTC naive
    prev_close: float | None = None
    open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    volume: int | None = None
    name: str | None = None
    currency: str = "INR"
    source: str = "unknown"
    delay_minutes: int | None = None   # what the vendor says about its own lag (0 = real-time); None = unknown


@dataclass(frozen=True)
class FundamentalsData:
    """Company-level figures that change quarterly, not by the second.

    Every field is optional and every one of them means "the vendor did not
    give us this" when it is None. Nothing here is ever derived, filled in or
    defaulted — a watchlist that guesses a P/E is worse than one that admits
    it does not know.
    """

    symbol: str
    source: str = "unknown"
    as_of: datetime | None = None          # vendor's own "most recent quarter" stamp
    market_cap: float | None = None
    pe_trailing: float | None = None
    pe_forward: float | None = None
    price_to_book: float | None = None
    eps_trailing: float | None = None
    book_value: float | None = None
    roe: float | None = None               # fraction, not percent
    dividend_yield: float | None = None    # fraction
    debt_to_equity: float | None = None    # vendor reports this as a percentage
    profit_margin: float | None = None     # fraction
    revenue_growth: float | None = None    # fraction, year on year
    beta: float | None = None

    def is_empty(self) -> bool:
        """True when the vendor answered but told us nothing usable. Callers
        must not store an all-None row: an empty row would look like a
        successful fetch and stop us retrying."""
        return all(getattr(self, f) is None for f in (
            "market_cap", "pe_trailing", "pe_forward", "price_to_book", "eps_trailing",
            "book_value", "roe", "dividend_yield", "debt_to_equity", "profit_margin",
            "revenue_growth", "beta"))


@dataclass(frozen=True)
class BarData:
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


class MarketDataProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def get_quotes(self, symbols: list[str]) -> dict[str, QuoteData]:
        """Return quotes for the symbols it could resolve. Missing symbols are
        simply absent (partial success is success). Raise ProviderError only
        when the provider as a whole is unusable."""

    @abstractmethod
    async def get_daily_bars(self, symbol: str, days: int = 365) -> list[BarData]:
        """Ascending daily bars, oldest first. Should exclude today's
        partial bar while the market is open (callers treat the last bar as
        a completed session)."""

    async def get_fundamentals(self, symbols: list[str]) -> dict[str, FundamentalsData]:
        """Optional. A provider that cannot supply fundamentals returns {} and
        the app shows "not available from this feed" rather than a blank that
        reads like a zero. Deliberately not abstract: fundamentals are a
        garnish, and no provider should be forced to fake them."""
        return {}
