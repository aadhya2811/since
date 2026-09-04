# 2-minute demo script

Record with the offline demo (`make demo` or `SINCE_PROVIDER=simulated SINCE_NEWS_PROVIDER=simulated uvicorn app.main:app`) so the scripted events are guaranteed to show, or with Yahoo during market hours if you want real prices.

| Time | Screen | Say |
|---|---|---|
| 0:00 | Login page | "Every watchlist shows what changed since yesterday's close. But you don't care about yesterday — you care about what changed since *you* last looked, and only about stocks whose move was unusual *for them*. That's Since." |
| 0:15 | Enter email → code on screen → sign in | "Passwordless login. Sign in on any device with the same email and your state follows you — that's how it persists across devices." |
| 0:25 | Create sample watchlist | "Twelve NSE stocks. First visit — so the baseline is set to now. Nothing has changed yet." |
| 0:35 | Click **3 sessions ago** | "This is the demo control: pretend I last looked three sessions ago. Now the screen is a briefing, not a table: two need attention, five worth a glance, five quiet." |
| 0:50 | Point at INDUSINDBK card | "Down 7.6% since Tuesday — and it tells me that's a 2.3σ move *for this stock* over 3 sessions, on 2.2× normal volume, four straight down days, and here's the headline that probably explains it. Every flag has its evidence inline." |
| 1:05 | Point at Suzlon vs a quiet one | "Suzlon is up 11% but that's only 1.7σ — it's a volatile name. Meanwhile a 2.5% drop in Hindustan Unilever scores 1.7σ too. Same σ, very different percentages. Fixed thresholds get this wrong." |
| 1:20 | Expand a card | "Detail: what I last saw and when, how unusual, 52-week range, news diffed against the same baseline, and price levels I set — 'tell me if it falls below 3,400'." Set a level. |
| 1:30 | Click **☆ pin** on two stocks | "Pin anything you always want visible — a tiny dashboard at the top, across all my lists. Click a tile, it jumps to the card." |
| 1:35 | Click **Seen it ✓** | "Acknowledge resets the baseline for that stock. Next time I come back, it diffs from here." |
| 1:45 | Status strip | "Every price carries its freshness — Yahoo's NSE feed is 15 minutes delayed, and the app says so instead of pretending. If the feed dies, a circuit breaker fails over to a simulated feed and a banner tells you." |
| 1:55 | (optional) open in a second tab / phone | "Same account on another device: same baselines, same acknowledgements. Edit the list on both at once and the loser gets a 409 and reloads — no lost updates." |
| 2:00 | README | "Architecture, every decision and trade-off, 34 tests. Thanks." |

## Judge-facing one-liner (for the submission form)

> A watchlist that opens as a briefing. It keeps a per-user baseline of what you last saw, scores every move as a z-score against that stock's own volatility over the sessions elapsed, and triages your list into needs-attention / worth-a-glance / quiet with plain-English reasons and the headline that likely explains each move. FastAPI + React, real NSE data with circuit-breaker fallback, optimistic concurrency across devices, 34 tests.
