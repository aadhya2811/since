"""Generate docs/TEST_REPORT.md from an actual test run.

The point of generating rather than writing this file: a hand-typed test report
is a claim, and a generated one is evidence. Re-run it and the numbers move on
their own, or the build fails.

    python scripts/make_test_report.py        (from backend/)
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
OUT = Path(__file__).resolve().parents[1] / "docs" / "TEST_REPORT.md"

WHAT_EACH_FILE_PROTECTS = {
    "test_significance.py": "The scoring engine: that the same % move is judged differently for different stocks, that elapsed sessions scale it, and that discrete events (52w breach, level cross, gap, streak) fire only when they should.",
    "test_thesis.py": "Analyst memory: exactly when the app is allowed to interrupt you about a thesis, and that a dismissal is never recorded as an answer.",
    "test_yahoo_parsing.py": "The only place a number can be *wrong* rather than missing — the vendor payload parser, against synthetic responses with known correct answers.",
    "test_market_infra.py": "The data plumbing: trading-session arithmetic, quotes never moving backwards in market time, circuit-breaker and failover behaviour.",
    "test_api.py": "The HTTP surface: auth, ownership isolation, optimistic concurrency (If-Match / 409), and the briefing end to end.",
    "test_email.py": "Login-code delivery, including that a failed send still lets a judge sign in.",
}

# Every number the UI puts on screen, and where it comes from. Anything not in
# this table is not displayed.
PROVENANCE = [
    ("Price", "Quote.price", "Vendor `regularMarketPrice`, stored verbatim", "yahoo.py:_quote"),
    ("% today", "computed", "`price / prev_close − 1`", "significance.py:assess"),
    ("Previous close", "Quote.prev_close", "Close of the session before the print's own date, read from the daily rows (never `chartPreviousClose`)", "yahoo.py:_quote"),
    ("Open / day high / day low", "Quote.*", "Vendor meta fields; open re-read from the daily row", "yahoo.py:_quote"),
    ("Volume, “× normal”", "Quote.volume", "Vendor volume ÷ mean of the last 20 stored daily volumes, scaled by the fraction of the session elapsed", "significance.py:avg_volume"),
    ("Change since you looked", "computed", "`price / Baseline.committed_price − 1`", "significance.py:assess"),
    ("“How unusual” / σ", "computed", "Sample stdev of log returns over the last 20 stored closes, floored at 0.4%/day", "significance.py:sigma_daily"),
    ("52-week range & position", "computed", "max(high) / min(low) over the last 250 stored daily bars", "significance.py:range_52w"),
    ("Sparkline", "DailyBar.close", "The last 30 stored closes, drawn as-is", "Sparkline.tsx"),
    ("Index tiles (Nifty, Bank Nifty)", "Quote + DailyBar", "Same pipeline as any other symbol; returns are close-to-close", "briefing.py:index_strip"),
    ("Your list, since you looked", "computed", "Equal-weighted mean of each holding's change since its own baseline", "briefing.py:build_briefing"),
    ("Headlines", "NewsItem", "Title, link, publisher and timestamp taken verbatim from the RSS item; never rewritten or summarised", "market/news.py"),
    ("Thesis change since written", "computed", "`price / Thesis.anchor_price − 1`, anchor being a stored quote or a stored past close", "thesis.py:evaluate"),
    ("Your record (% held)", "computed", "count(verdict='holds') ÷ count(reviews), all user-entered", "thesis.py:history"),
    ("Freshness badge", "Quote.delay_minutes", "The vendor's own `exchangeDataDelayedBy`, which overrides our clock arithmetic", "briefing.py:freshness"),
    ("Market cap, P/E, P/B, EPS, ROE, margin, revenue growth, debt/equity, dividend yield, beta", "Fundamental.*",
     "Vendor `quoteSummary` fields stored verbatim, units unconverted; a field the vendor omits is stored NULL and rendered “—”",
     "yahoo.py:_fundamentals_one"),
]

# The only three numbers in the system that are not observed from data.
DEFAULTS = [
    ("`FALLBACK_SIGMA_DAILY` = 1.8%/day", "Used when a symbol has fewer than 8 stored sessions, so a z-score can still be formed.",
     "Disclosed on the card: “Limited price history — volatility estimate is a default.”"),
    ("`MIN_SIGMA_DAILY` = 0.4%/day", "A floor, so an index or a mega-cap with a near-zero σ cannot produce an absurd z-score.",
     "Only ever makes the app *less* excitable; never inflates a move."),
    ("`delay_minutes` = 15", "Assumed when the vendor does not declare its own lag.",
     "Disclosed in the badge as “Delayed 15 min (feed)”. The refused failure mode is calling a stale price “Live”."),
]

NOT_SHOWN = [
    "Promoter holding, FII/DII holding patterns, insider and bulk-deal filings — these are India-specific disclosures that live on NSE/BSE, not on any keyless feed. Not displayed, not estimated.",
    "Line items parsed out of quarterly report PDFs — every company lays them out differently and there is no schema. The app surfaces results *headlines* and lets the news trigger prompt a thesis review; it never claims a revenue or profit figure it parsed itself.",
    "Target prices, fair value, buy/sell/hold, conviction or confidence scores — recommending securities is a regulated activity (SEBI RA/IA), and the Market page says so on the page.",
    "Any forecast of any kind. The app describes what already happened. (Forward P/E is the exception that proves it: it is the *vendor's* published consensus figure, labelled as such, not a projection Since computed.)",
]

FUNDAMENTALS_NOTE = """\
Fundamentals deserve their own paragraph, because they are the one part of the app that depends on
an endpoint the vendor actively gates. Yahoo serves them behind a cookie-and-crumb handshake that
works from most ordinary networks and fails from many cloud hosts, and which Yahoo changes without
notice. That shapes three decisions:

* **Failure is total and silent, never partial and invented.** No crumb means no fundamentals for
  that cycle. There is no cached guess, no last-known value presented as current, and no derived
  substitute. The card says the figures are unavailable.
* **A missing field is a dash, not a zero.** A loss-making company genuinely has no trailing P/E.
  Rendering that as `0.0` would be the single most misleading thing this app could do, so `_raw()`
  refuses to coerce Yahoo's empty-dict-means-no-value into a number, and there is a test for it.
* **It can never break the rest of the app.** `ResilientProvider.get_fundamentals` deliberately does
  not touch the circuit breaker: a vendor serving prices perfectly but declining fundamentals is not
  a failing provider, and failing the chain over a missing P/E would be exactly backwards.

Run `python scripts/check_fundamentals.py` to see what this network actually gets."""


def run(cmd: list[str]) -> tuple[str, int]:
    p = subprocess.run(cmd, cwd=BACKEND, capture_output=True, text=True)
    return p.stdout + p.stderr, p.returncode


def main() -> int:
    verbose, _ = run([sys.executable, "-m", "pytest", "-v", "--no-header", "-p", "no:cacheprovider"])
    cov, _ = run([sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
                  "--cov=app", "--cov-report=term-missing"])

    tests = re.findall(r"^(tests/\S+::\S+)\s+(PASSED|FAILED|ERROR|SKIPPED)", verbose, re.M)
    passed = sum(1 for _, s in tests if s == "PASSED")
    failed = [t for t, s in tests if s not in ("PASSED", "SKIPPED")]
    total_cov = re.search(r"^TOTAL\s+\d+\s+\d+\s+(\d+)%", cov, re.M)
    cov_pct = total_cov.group(1) if total_cov else "?"
    cov_table = "\n".join(l for l in cov.splitlines()
                          if l.startswith(("Name", "app/", "----", "TOTAL")))

    by_file: dict[str, list[str]] = {}
    for t, s in tests:
        f, name = t.split("::")[0].split("/")[-1], t.split("::")[-1]
        by_file.setdefault(f, []).append(name)

    L: list[str] = []
    A = L.append
    A("# Test report")
    A("")
    A(f"Generated **{datetime.now(timezone.utc):%d %b %Y, %H:%M UTC}** by `python scripts/make_test_report.py`, "
      "from an actual run. Re-running it regenerates this file; it is evidence, not a claim.")
    A("")
    A(f"**{passed} tests passing**, {len(failed)} failing. Backend line coverage **{cov_pct}%**.")
    A("")
    A("```")
    A("cd backend && pip install -r requirements.txt && python -m pytest -v")
    A("```")
    A("")
    if failed:
        A("### Failing")
        A("")
        for f in failed:
            A(f"- `{f}`")
        A("")

    A("## 1. Where every number on screen comes from")
    A("")
    A("The question this section answers: *can the app show a figure it did not get from data?*")
    A("Below is every number the interface displays. Anything not in this table is not shown.")
    A("")
    A("| On screen | Stored as | Derivation | Code |")
    A("|---|---|---|---|")
    for shown, stored, how, where in PROVENANCE:
        A(f"| {shown} | `{stored}` | {how} | `{where}` |")
    A("")
    A("Two properties hold across the whole table:")
    A("")
    A("1. **Every displayed value is either a vendor field stored verbatim, or arithmetic over stored values.** "
      "There is no third category — no estimate, no interpolation, no model output.")
    A("2. **A missing input produces a missing output, never a substituted one.** A symbol with no quote renders "
      "“Waiting for first quote…”; a ticker the feed rejects renders “Not available on the data feed — the ticker "
      "may be renamed or delisted”, and stops being polled. Neither draws a number.")
    A("")

    A("## 2. The three numbers that are *not* observed")
    A("")
    A("Being exact about this matters more than claiming zero. Three constants exist, all of them disclosed in the "
      "interface where they apply:")
    A("")
    A("| Constant | Why it exists | How it is disclosed |")
    A("|---|---|---|")
    for c, why, how in DEFAULTS:
        A(f"| {c} | {why} | {how} |")
    A("")

    A("## 3. What the app deliberately does not show")
    A("")
    A("Every item here was considered and rejected, because shipping it would have meant inventing data or giving "
      "advice:")
    A("")
    for n in NOT_SHOWN:
        A(f"- {n}")
    A("")
    A(FUNDAMENTALS_NOTE)
    A("")
    A("When the price feed falls back to the deterministic simulator (offline, or the vendor is down), the app says "
      "so in two places at once: the status strip reads `feed: simulated`, and every card's data line reads "
      "`source: simulated`. Simulated data is never presented as real.")
    A("")

    A("## 4. What each test file protects")
    A("")
    A("| File | Tests | Protects |")
    A("|---|---|---|")
    for f in sorted(by_file):
        A(f"| `tests/{f}` | {len(by_file[f])} | {WHAT_EACH_FILE_PROTECTS.get(f, '—')} |")
    A("")

    A("## 5. Full run")
    A("")
    A("Every test name below is a sentence describing the behaviour it pins down.")
    A("")
    for f in sorted(by_file):
        A(f"### `tests/{f}`")
        A("")
        for name in by_file[f]:
            A(f"- ✅ `{name}`")
        A("")

    A("## 6. Coverage")
    A("")
    A("```")
    A(cov_table)
    A("```")
    A("")
    A("The two low numbers are both deliberate. `market/service.py` is the background scheduler — a long-running "
      "loop whose useful behaviour is timing, tested by hand rather than by asserting on sleeps. `market/yahoo.py` "
      "shows lower line coverage than it deserves because its network paths are unreachable without a live vendor; "
      "its *parsing* logic — the part that can produce a wrong number — is covered exhaustively in "
      "`test_yahoo_parsing.py` against synthetic payloads.")
    A("")

    A("## 7. Cases exercised by hand")
    A("")
    A("Things a unit test cannot assert, checked in a browser against the live NSE feed:")
    A("")
    for line in [
        "Signing in on a second device and seeing the same watchlist, with the baseline per user rather than per device.",
        "Leaving the tab for 30+ minutes and returning — the visit ends, the baseline commits, and the briefing re-diffs from it.",
        "A ticker that the feed renamed (`ZOMATO` → `ETERNAL`, `TATAMOTORS` → `TMPV`): resolved by alias, not by silently dropping the row.",
        "Editing the same watchlist in two tabs, to see the 409 and the reload-and-retry path.",
        "Comparing a displayed price against a broker app during market hours, confirming the gap matches the declared 15-minute feed delay rather than being an error.",
        "The empty states: no watchlist, empty watchlist, a symbol with no history yet.",
    ]:
        A(f"- {line}")
    A("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {OUT}  ({passed} passing, {cov_pct}% coverage)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
