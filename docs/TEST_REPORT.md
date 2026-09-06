# Test report

Generated **06 Sep 2026, 13:55 UTC** by `python scripts/make_test_report.py`, from an actual run. Re-running it regenerates this file; it is evidence, not a claim.

**80 tests passing**, 0 failing. Backend line coverage **85%**.

```
cd backend && pip install -r requirements.txt && python -m pytest -v
```

## 1. Where every number on screen comes from

The question this section answers: *can the app show a figure it did not get from data?*
Below is every number the interface displays. Anything not in this table is not shown.

| On screen | Stored as | Derivation | Code |
|---|---|---|---|
| Price | `Quote.price` | Vendor `regularMarketPrice`, stored verbatim | `yahoo.py:_quote` |
| % today | `computed` | `price / prev_close − 1` | `significance.py:assess` |
| Previous close | `Quote.prev_close` | Close of the session before the print's own date, read from the daily rows (never `chartPreviousClose`) | `yahoo.py:_quote` |
| Open / day high / day low | `Quote.*` | Vendor meta fields; open re-read from the daily row | `yahoo.py:_quote` |
| Volume, “× normal” | `Quote.volume` | Vendor volume ÷ mean of the last 20 stored daily volumes, scaled by the fraction of the session elapsed | `significance.py:avg_volume` |
| Change since you looked | `computed` | `price / Baseline.committed_price − 1` | `significance.py:assess` |
| “How unusual” / σ | `computed` | Sample stdev of log returns over the last 20 stored closes, floored at 0.4%/day | `significance.py:sigma_daily` |
| 52-week range & position | `computed` | max(high) / min(low) over the last 250 stored daily bars | `significance.py:range_52w` |
| Sparkline | `DailyBar.close` | The last 30 stored closes, drawn as-is | `Sparkline.tsx` |
| Index tiles (Nifty, Bank Nifty) | `Quote + DailyBar` | Same pipeline as any other symbol; returns are close-to-close | `briefing.py:index_strip` |
| Your list, since you looked | `computed` | Equal-weighted mean of each holding's change since its own baseline | `briefing.py:build_briefing` |
| Headlines | `NewsItem` | Title, link, publisher and timestamp taken verbatim from the RSS item; never rewritten or summarised | `market/news.py` |
| Thesis change since written | `computed` | `price / Thesis.anchor_price − 1`, anchor being a stored quote or a stored past close | `thesis.py:evaluate` |
| Your record (% held) | `computed` | count(verdict='holds') ÷ count(reviews), all user-entered | `thesis.py:history` |
| Freshness badge | `Quote.delay_minutes` | The vendor's own `exchangeDataDelayedBy`, which overrides our clock arithmetic | `briefing.py:freshness` |
| Market cap, P/E, P/B, EPS, ROE, margin, revenue growth, debt/equity, dividend yield, beta | `Fundamental.*` | Vendor `quoteSummary` fields stored verbatim, units unconverted; a field the vendor omits is stored NULL and rendered “—” | `yahoo.py:_fundamentals_one` |

Two properties hold across the whole table:

1. **Every displayed value is either a vendor field stored verbatim, or arithmetic over stored values.** There is no third category — no estimate, no interpolation, no model output.
2. **A missing input produces a missing output, never a substituted one.** A symbol with no quote renders “Waiting for first quote…”; a ticker the feed rejects renders “Not available on the data feed — the ticker may be renamed or delisted”, and stops being polled. Neither draws a number.

## 2. The three numbers that are *not* observed

Being exact about this matters more than claiming zero. Three constants exist, all of them disclosed in the interface where they apply:

| Constant | Why it exists | How it is disclosed |
|---|---|---|
| `FALLBACK_SIGMA_DAILY` = 1.8%/day | Used when a symbol has fewer than 8 stored sessions, so a z-score can still be formed. | Disclosed on the card: “Limited price history — volatility estimate is a default.” |
| `MIN_SIGMA_DAILY` = 0.4%/day | A floor, so an index or a mega-cap with a near-zero σ cannot produce an absurd z-score. | Only ever makes the app *less* excitable; never inflates a move. |
| `delay_minutes` = 15 | Assumed when the vendor does not declare its own lag. | Disclosed in the badge as “Delayed 15 min (feed)”. The refused failure mode is calling a stale price “Live”. |

## 3. What the app deliberately does not show

Every item here was considered and rejected, because shipping it would have meant inventing data or giving advice:

- Promoter holding, FII/DII holding patterns, insider and bulk-deal filings — these are India-specific disclosures that live on NSE/BSE, not on any keyless feed. Not displayed, not estimated.
- Line items parsed out of quarterly report PDFs — every company lays them out differently and there is no schema. The app surfaces results *headlines* and lets the news trigger prompt a thesis review; it never claims a revenue or profit figure it parsed itself.
- Target prices, fair value, buy/sell/hold, conviction or confidence scores — recommending securities is a regulated activity (SEBI RA/IA), and the Market page says so on the page.
- Any forecast of any kind. The app describes what already happened. (Forward P/E is the exception that proves it: it is the *vendor's* published consensus figure, labelled as such, not a projection Since computed.)

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

Run `python scripts/check_fundamentals.py` to see what this network actually gets.

When the price feed falls back to the deterministic simulator (offline, or the vendor is down), the app says so in two places at once: the status strip reads `feed: simulated`, and every card's data line reads `source: simulated`. Simulated data is never presented as real.

## 4. What each test file protects

| File | Tests | Protects |
|---|---|---|
| `tests/test_api.py` | 18 | The HTTP surface: auth, ownership isolation, optimistic concurrency (If-Match / 409), and the briefing end to end. |
| `tests/test_email.py` | 6 | Login-code delivery, including that a failed send still lets a judge sign in. |
| `tests/test_market_infra.py` | 8 | The data plumbing: trading-session arithmetic, quotes never moving backwards in market time, circuit-breaker and failover behaviour. |
| `tests/test_significance.py` | 13 | The scoring engine: that the same % move is judged differently for different stocks, that elapsed sessions scale it, and that discrete events (52w breach, level cross, gap, streak) fire only when they should. |
| `tests/test_thesis.py` | 17 | Analyst memory: exactly when the app is allowed to interrupt you about a thesis, and that a dismissal is never recorded as an answer. |
| `tests/test_yahoo_parsing.py` | 18 | The only place a number can be *wrong* rather than missing — the vendor payload parser, against synthetic responses with known correct answers. |

## 5. Full run

Every test name below is a sentence describing the behaviour it pins down.

### `tests/test_api.py`

- ✅ `test_login_flow_and_bad_codes`
- ✅ `test_two_devices_share_one_account`
- ✅ `test_stale_version_gets_409_with_current_state`
- ✅ `test_add_and_remove_are_idempotent`
- ✅ `test_cannot_touch_someone_elses_watchlist`
- ✅ `test_baseline_advances_on_new_visit_not_on_refresh`
- ✅ `test_idle_timeout_starts_a_new_visit_even_with_same_visit_id`
- ✅ `test_acknowledge_resets_baseline_immediately`
- ✅ `test_rewind_sets_baseline_to_a_past_close`
- ✅ `test_level_crossing_surfaces_in_briefing`
- ✅ `test_briefing_survives_provider_outage_with_stale_data`
- ✅ `test_news_is_diffed_against_baseline_and_attached_to_moves`
- ✅ `test_unknown_ticker_is_rejected_and_delisted_one_is_flagged`
- ✅ `test_old_ticker_names_resolve_to_new_ones`
- ✅ `test_vendor_declared_delay_beats_live_label`
- ✅ `test_pins_form_a_cross_watchlist_board`
- ✅ `test_market_compare_and_news_pages`
- ✅ `test_news_scopes_market_wide_company_and_all`

### `tests/test_email.py`

- ✅ `test_unconfigured_mailer_falls_back_to_the_screen`
- ✅ `test_configured_mailer_builds_a_real_message_and_sends_it`
- ✅ `test_a_broken_mail_server_never_locks_anyone_out`
- ✅ `test_api_shows_the_code_when_email_is_off_and_hides_it_once_delivered`
- ✅ `test_a_failed_send_still_returns_the_code_so_sign_in_works`
- ✅ `test_requesting_codes_for_one_address_is_rate_limited`

### `tests/test_market_infra.py`

- ✅ `test_market_state_phases`
- ✅ `test_sessions_between_skips_weekends_and_holidays`
- ✅ `test_quote_never_moves_backwards_in_market_time`
- ✅ `test_same_print_conflict_primary_wins`
- ✅ `test_bars_upsert_is_idempotent_and_corrects`
- ✅ `test_breaker_opens_after_threshold_and_half_opens_after_reset`
- ✅ `test_resilient_provider_fails_over_and_reports_degraded`
- ✅ `test_symbol_not_found_does_not_trip_breaker_or_fall_back`

### `tests/test_significance.py`

- ✅ `test_same_percent_move_is_judged_by_the_stocks_own_volatility`
- ✅ `test_move_is_scaled_by_sessions_elapsed`
- ✅ `test_no_new_print_means_no_move_reason`
- ✅ `test_level_crossed_in_either_direction_and_not_otherwise`
- ✅ `test_52_week_high_is_attention_even_on_a_small_move`
- ✅ `test_volume_ratio_is_session_adjusted_while_open`
- ✅ `test_gap_open_is_reported_only_when_large`
- ✅ `test_short_history_falls_back_to_default_sigma_and_says_so`
- ✅ `test_sigma_has_a_floor_so_indices_dont_explode`
- ✅ `test_streak_counts_direction_runs`
- ✅ `test_reasons_are_ordered_move_first_then_events`
- ✅ `test_market_wide_moves_are_discounted_and_against_market_is_flagged`
- ✅ `test_no_new_print_is_flagged_as_such_not_reported_as_a_zero_move`

### `tests/test_thesis.py`

- ✅ `test_quiet_thesis_is_not_a_prompt`
- ✅ `test_statistically_rare_move_asks_you_to_re_read_it`
- ✅ `test_the_same_move_on_a_wilder_stock_is_not_a_trigger`
- ✅ `test_a_material_move_prompts_even_when_it_is_not_statistically_rare`
- ✅ `test_material_threshold_still_respects_the_stock_s_own_range`
- ✅ `test_52_week_high_outranks_the_move_reason`
- ✅ `test_news_burst_triggers_below_the_move_threshold`
- ✅ `test_horizon_expiry_is_the_last_resort`
- ✅ `test_snooze_silences_soft_triggers_but_not_a_52_week_breach`
- ✅ `test_closed_theses_never_prompt`
- ✅ `test_thesis_lifecycle`
- ✅ `test_editing_the_reason_re_anchors_it`
- ✅ `test_demo_rewind_uses_a_real_past_close_not_an_invented_one`
- ✅ `test_snooze_defers_without_recording_a_review`
- ✅ `test_deleting_a_thesis_removes_it_and_its_reviews`
- ✅ `test_rejects_verdicts_and_text_it_does_not_understand`
- ✅ `test_thesis_is_private_to_its_owner`

### `tests/test_yahoo_parsing.py`

- ✅ `test_prev_close_comes_from_yesterdays_row_not_chart_previous_close`
- ✅ `test_prev_close_skips_null_rows_for_holidays_and_halts`
- ✅ `test_falls_back_to_meta_previous_close_only_when_no_row_matches`
- ✅ `test_day_change_is_computed_from_the_derived_prev_close`
- ✅ `test_vendor_declared_delay_is_carried_through_verbatim`
- ✅ `test_missing_delay_assumes_delayed_never_live`
- ✅ `test_a_quote_without_a_price_is_dropped_not_defaulted`
- ✅ `test_unknown_ticker_raises_symbol_not_found_not_provider_error`
- ✅ `test_rate_limit_and_server_errors_are_provider_errors`
- ✅ `test_malformed_payload_is_an_error_not_a_silent_zero`
- ✅ `test_bars_drop_null_rows_and_keep_real_ones`
- ✅ `test_fundamentals_are_parsed_with_their_units_intact`
- ✅ `test_absent_fields_are_none_and_never_zero`
- ✅ `test_a_response_with_nothing_usable_is_not_stored_as_a_row`
- ✅ `test_string_and_boolean_junk_is_rejected_rather_than_coerced`
- ✅ `test_a_rejected_crumb_clears_it_so_the_next_cycle_refetches`
- ✅ `test_no_crumb_means_no_fundamentals_not_an_exception`
- ✅ `test_an_html_error_page_is_never_mistaken_for_a_crumb`

## 6. Coverage

```
Name                         Stmts   Miss  Cover   Missing
----------------------------------------------------------
app/__init__.py                  0      0   100%
app/auth.py                     74      7    91%   69-71, 104, 107, 110-111
app/config.py                   35      0   100%
app/db.py                       59      9    85%   56-58, 80, 85-89
app/engine/__init__.py           0      0   100%
app/engine/analytics.py        150      9    94%   34, 36, 42, 49, 136, 169-170, 214, 239
app/engine/baselines.py         52      2    96%   43, 78
app/engine/briefing.py         168     21    88%   24, 28-35, 40, 69, 74, 76, 119, 151-152, 202-205, 224, 240
app/engine/significance.py     238      7    97%   128, 157, 176, 183, 190, 294, 298
app/engine/thesis.py           139      5    96%   97, 104, 158, 219, 314
app/mailer.py                   70     14    80%   63, 107-120
app/main.py                     43      4    91%   58-61
app/market/__init__.py           0      0   100%
app/market/calendar.py          63      4    94%   104-107
app/market/news.py             112     45    60%   73-80, 87-88, 91-124, 206, 212, 224, 228
app/market/provider.py          56      1    98%   104
app/market/resilient.py         83     15    82%   64, 87-91, 110-118
app/market/service.py          310    179    42%   48-58, 62-76, 99, 103-108, 115-124, 128-225, 232-235, 241, 268-271, 286-311, 315, 327-330, 342, 358, 361-364, 369-373, 380-381, 397-403, 407-414
app/market/simulated.py        103     21    80%   50-51, 110-131, 171
app/market/store.py            117     20    83%   45, 73, 79, 107, 119, 125-128, 148, 164-175, 182
app/market/universe.py          33      2    94%   103, 118
app/market/yahoo.py            183     52    72%   55-56, 68-71, 74, 80-81, 122-137, 157, 173, 176, 184-185, 187-188, 196-197, 202, 204, 207-208, 210, 241, 247-258, 264-265
app/models.py                  176      0   100%
app/routers/__init__.py          0      0   100%
app/routers/auth.py             35      2    94%   57-58
app/routers/briefing.py         82      7    91%   49, 64-68, 93
app/routers/misc.py             39      1    97%   56
app/routers/thesis.py          107      5    95%   42, 71, 87, 105, 145
app/routers/watchlists.py      151     31    79%   58-59, 127-135, 141-143, 161-162, 201-215
app/schemas.py                 325      0   100%
app/util.py                     16      3    81%   14-16
----------------------------------------------------------
TOTAL                         3019    466    85%
```

The two low numbers are both deliberate. `market/service.py` is the background scheduler — a long-running loop whose useful behaviour is timing, tested by hand rather than by asserting on sleeps. `market/yahoo.py` shows lower line coverage than it deserves because its network paths are unreachable without a live vendor; its *parsing* logic — the part that can produce a wrong number — is covered exhaustively in `test_yahoo_parsing.py` against synthetic payloads.

## 7. Cases exercised by hand

Things a unit test cannot assert, checked in a browser against the live NSE feed:

- Signing in on a second device and seeing the same watchlist, with the baseline per user rather than per device.
- Leaving the tab for 30+ minutes and returning — the visit ends, the baseline commits, and the briefing re-diffs from it.
- A ticker that the feed renamed (`ZOMATO` → `ETERNAL`, `TATAMOTORS` → `TMPV`): resolved by alias, not by silently dropping the row.
- Editing the same watchlist in two tabs, to see the 409 and the reload-and-retry path.
- Comparing a displayed price against a broker app during market hours, confirming the gap matches the declared 15-minute feed delay rather than being an error.
- The empty states: no watchlist, empty watchlist, a symbol with no history yet.

