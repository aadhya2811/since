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
