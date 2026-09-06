"""Does the fundamentals feed work from *this* machine and network?

Fundamentals (P/E, ROE, market cap…) come from a Yahoo endpoint that is gated
behind a cookie + crumb handshake. That handshake works from most home and
office networks and fails from a lot of cloud and datacentre IPs, and Yahoo
changes it without notice. Everything else in Since — prices, history, news,
the briefing, analyst memory — is unaffected either way.

So rather than have you find out mid-demo, run this:

    cd backend && python ../scripts/check_fundamentals.py

It reports, per symbol, exactly what came back. Nothing is written to the
database and nothing is cached; this only tells you whether to expect the
Fundamentals block to be populated or to show its "not available" state.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.market.yahoo import YahooProvider  # noqa: E402

SYMBOLS = sys.argv[1:] or ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "SUZLON.NS"]

FIELDS = [
    ("market cap", "market_cap", lambda v: f"₹{v / 1e7:,.0f} cr"),
    ("P/E", "pe_trailing", lambda v: f"{v:.1f}"),
    ("P/B", "price_to_book", lambda v: f"{v:.2f}"),
    ("EPS", "eps_trailing", lambda v: f"₹{v:,.2f}"),
    ("ROE", "roe", lambda v: f"{v * 100:.1f}%"),
    ("debt/equity", "debt_to_equity", lambda v: f"{v:.0f}%"),
    ("div yield", "dividend_yield", lambda v: f"{v * 100:.2f}%"),
]


async def main() -> int:
    p = YahooProvider(timeout=12.0)

    print(f"Asking Yahoo for fundamentals on {len(SYMBOLS)} symbols…\n")
    try:
        got = await p.get_fundamentals(SYMBOLS)
    except Exception as e:                      # noqa: BLE001 — this script reports, it does not raise
        print(f"  the whole request failed: {type(e).__name__}: {e}")
        got = {}

    if not got:
        print("  ✗ No fundamentals available from this network.")
        print()
        print("  This is the expected outcome on many cloud hosts and some corporate")
        print("  networks: Yahoo declined to issue the crumb token, or rejected it.")
        print("  Since handles this on purpose — the Fundamentals block on each card")
        print("  will read 'not available from the free feed' instead of showing")
        print("  blanks that look like zeros. Prices, history, news, the briefing")
        print("  and analyst memory are all unaffected.")
        return 1

    for sym in SYMBOLS:
        f = got.get(sym)
        if f is None:
            print(f"  {sym:<14} ✗ nothing returned for this symbol")
            continue
        have = [(label, fmt(getattr(f, attr))) for label, attr, fmt in FIELDS if getattr(f, attr) is not None]
        missing = [label for label, attr, _ in FIELDS if getattr(f, attr) is None]
        print(f"  {sym:<14} ✓ {', '.join(f'{k} {v}' for k, v in have)}")
        if missing:
            print(f"  {'':<14}   no value for: {', '.join(missing)} (shown as “—”, never as 0)")
        if f.as_of:
            print(f"  {'':<14}   quarter ending {f.as_of:%d %b %Y}")

    print(f"\n  {len(got)}/{len(SYMBOLS)} symbols returned data. The Fundamentals block will populate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
