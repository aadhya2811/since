# Demo script

Two minutes is about 300 spoken words. That is enough for **one idea, proved twice** — not a tour. So this script leads with the thesis, proves it with the scoring, then spends its remaining time on the two things nothing else in the category does: **analyst memory**, and **being honest about data**. Everything else is in the overflow section, to use only if the format allows more.

---

## Before you record

**Warm the data first.** Run the backend once and leave it up for two or three minutes before you hit record, so quotes, history, news and fundamentals are all in the database. A demo that opens on empty skeletons loses ten seconds you do not have.

```powershell
cd backend
.\run.ps1
# leave it running, open http://localhost:8000, then:
python ..\scripts\check_fundamentals.py    # confirm the fundamentals block will populate
```

**Use the real feed.** Yahoo works from your network, so record with real NSE prices — "this is live market data" is worth more than a perfectly scripted move. The demo rewind works identically on real stored history, so you do not need the market to be open. If Yahoo is down when you record, `SINCE_PROVIDER=simulated` gives you the same script with deterministic scripted events, and the status strip will say `feed: simulated` — which is itself the honesty point at 1:45.

**Have this ready before recording:** a sample watchlist created, two stocks pinned, and **one thesis already written** on a stock you will feature — then run its "Try it → 90 sessions ago" so the review prompt is showing when you arrive. Writing a thesis live costs 20 seconds you cannot spare.

---

## The 2:00 script

| Time | Screen | Say |
|---|---|---|
| **0:00** | Briefing, already signed in | "Every watchlist shows you what changed since yesterday's close. But you don't care about yesterday. You care about what changed since **you** last looked — and only about the moves that are unusual **for that stock**." |
| **0:12** | Point at the headline + command strip | "So Since opens as a briefing, not a table. Two need attention, nine worth a glance, the rest quiet. Nifty and your list's net move up top, and one number for how many of your own investment reasons need re-reading — I'll come back to that." |
| **0:25** | Click **Try it → 3 sessions ago** | "This is a demo control: pretend I last checked three sessions ago. Everything now re-diffs from that point, because the baseline is per-user, not per-day." |
| **0:35** | Point at two cards side by side | "Here's the whole argument. Suzlon is up 11% — that's **1.7σ**, ordinary for a stock that swings this much. Hindustan Unilever is down 2.5% — also **1.7σ**, because it never moves. Same significance, wildly different percentages. Any watchlist using a fixed 5% threshold gets both of these wrong." |
| **0:50** | Expand a card | "Every flag carries its evidence: how unusual, against what normal, volume versus its own 20-day average, the 52-week range, and the headline that probably explains it — flagged new because **I** hadn't seen it, not because it's recent." |
| **1:02** | Scroll to Fundamentals | "Fundamentals too — P/E, ROE, margins, market cap, with the quarter they were reported for. And check this: P/E times EPS equals the price on the card, to the paisa. Those come from two different endpoints. They agree because nothing here is estimated." |
| **1:15** | Scroll to **Your reason** — prompt showing | "Now the part I actually care about. When you add a stock you write down **why**, in one sentence. Since timestamps it and leaves you alone — until something happens that earns the right to interrupt." |
| **1:25** | Read the prompt aloud | "Three months later it shows me my own words back, above the price, and asks: *does this still hold?* Everybody remembers the price they bought at. Almost nobody remembers why — which is the only way to tell a broken thesis from a bad week." |
| **1:38** | Click **Memory** in the nav | "Answer it and it goes on your record: how often your reasons actually survived. Not P&L, which conflates being right with being lucky." |
| **1:48** | Point at the freshness badge and a "—" | "And it never pretends. Yahoo's NSE feed is 15 minutes delayed and the badge says so. A field the vendor didn't give us is a dash, never a zero — a loss-making company has no P/E, and printing 0.0 there would be the most misleading thing this app could do." |
| **1:57** | Cut | "Eighty tests, and a README that argues for every decision. Thanks." |

---

## If you get 3 minutes instead

Insert after 1:38, in this order — most distinctive first:

| Screen | Say |
|---|---|
| **Market** page | "A wider view: sector performance, and the **most unusual** moves across sixty NSE names — ranked by how strange each move is for that stock, not by percent. It describes what happened; it doesn't tell you what to buy, because that's a regulated activity and the page says so." |
| **News** page | "Market-wide, your stocks, and the index heavyweights, in one feed — with 'new' measured against the same personal baseline." |
| **Compare** page | "Two or three names indexed to the same starting point, plus volatility, drawdown and correlation." |
| Pinned strip + a price level | "Pin anything you always want visible. Set a level — 'tell me if TCS falls below 3,400' — and crossing it in either direction is news." |
| A second tab | "Same account, another device: same baselines. Edit the list in both at once and the loser gets a 409 and reloads. No lost updates." |

---

## Questions you should have answers ready for

**"How do you know the numbers are right?"**
`docs/TEST_REPORT.md` is generated from an actual test run, not written by hand. It has a table of every number the interface displays and where each one comes from. Every value is either a vendor field stored verbatim or arithmetic over stored values — there's no third category. Exactly three constants aren't observed from data, and all three are named in that document and disclosed in the UI.

**"What's the hardest thing you got wrong?"**
Reusing the volatility-normalised score for the thesis reviews. Because z divides by √n, a stock that bled 26% over a quarter scored 1.2σ and would never have prompted anyone. Volatility-normalising is right for **attention** — that's the briefing's job minute to minute — and wrong for **conviction**, where what matters is the size of the outcome, not how surprising it is. So a move now triggers if it's rare **or** material. I found it by testing, not by reasoning.

**"Why no chatbot / buy recommendations?"**
The chatbot needs an API key you don't have, costs money per query, and can hallucinate numbers the app otherwise gets right from a real feed. Buy recommendations are SEBI Research Analyst territory. Both are in README §8 under what I deliberately didn't build.

**"What would you do next?"**
Promoter holding and FII/DII flows — the India-specific disclosures Yahoo doesn't carry. They need NSE/BSE scraping, which I wasn't willing to ship untested.

---

## Judge-facing one-liner (for the submission form)

> A watchlist that opens as a briefing. It keeps a per-user baseline of what you last saw and scores every move as a z-score against that stock's own volatility over the sessions elapsed, so a 3% move in a quiet blue-chip outranks 11% in a volatile small-cap. It also remembers **why** you added each stock and asks whether that reason still holds when the market gives it cause to — then keeps your record of how often you were right. Real NSE prices, news and fundamentals with circuit-breaker fallback and an honest "—" wherever the feed has no value; FastAPI + React, optimistic concurrency across devices, 80 tests and a generated data-provenance report.
