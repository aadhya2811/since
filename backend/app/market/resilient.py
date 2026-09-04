"""Circuit breaker + fallback chain around providers.

Behaviour
* Each provider has its own breaker. After N consecutive failures it opens
  and is skipped for `reset_seconds`; then one trial call is allowed
  (half-open). Success closes it.
* `get_quotes` walks the chain and returns the first provider's result. If
  every provider fails, ProviderError propagates — the *store* keeps serving
  the last good snapshot, marked stale. Users see old data labelled old,
  never an empty screen.
* `status()` is exposed on /health so the UI can show "running on simulated
  data" honestly.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from .provider import BarData, MarketDataProvider, ProviderError, QuoteData

log = logging.getLogger(__name__)


@dataclass
class Breaker:
    threshold: int = 3
    reset_seconds: float = 90.0
    failures: int = 0
    opened_at: float | None = None
    last_error: str | None = None
    _clock: callable = field(default=time.monotonic, repr=False)

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        if self._clock() - self.opened_at >= self.reset_seconds:
            return "half-open"
        return "open"

    def allow(self) -> bool:
        return self.state != "open"

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None
        self.last_error = None

    def record_failure(self, err: Exception) -> None:
        self.failures += 1
        self.last_error = str(err)[:200]
        if self.failures >= self.threshold:
            self.opened_at = self._clock()


class ResilientProvider(MarketDataProvider):
    name = "resilient"

    def __init__(self, chain: list[MarketDataProvider], threshold: int = 3, reset_seconds: float = 90.0):
        if not chain:
            raise ValueError("provider chain must not be empty")
        self.chain = chain
        self.breakers = {p.name: Breaker(threshold, reset_seconds) for p in chain}
        self.active: str = chain[0].name  # which provider served the last successful call

    async def _run(self, fn_name: str, *args):
        last_err: Exception | None = None
        for p in self.chain:
            br = self.breakers[p.name]
            if not br.allow():
                continue
            try:
                result = await getattr(p, fn_name)(*args)
            except ProviderError as e:
                br.record_failure(e)
                last_err = e
                log.warning("provider %s failed (%s): %s [breaker %s]", p.name, fn_name, e, br.state)
                continue
            except Exception as e:  # a bug in a provider must not take the app down
                br.record_failure(e)
                last_err = e
                log.exception("provider %s raised unexpectedly", p.name)
                continue
            br.record_success()
            if self.active != p.name:
                log.warning("market data now served by %s", p.name)
            self.active = p.name
            return result
        raise ProviderError(f"all providers failed: {last_err}")

    async def get_quotes(self, symbols: list[str]) -> dict[str, QuoteData]:
        return await self._run("get_quotes", symbols)

    async def get_daily_bars(self, symbol: str, days: int = 365) -> list[BarData]:
        return await self._run("get_daily_bars", symbol, days)

    def status(self) -> dict:
        primary = self.chain[0].name
        return {
            "active": self.active,
            "degraded": self.active != primary,
            "providers": [
                {"name": p.name, "breaker": self.breakers[p.name].state, "failures": self.breakers[p.name].failures,
                 "last_error": self.breakers[p.name].last_error}
                for p in self.chain
            ],
        }
