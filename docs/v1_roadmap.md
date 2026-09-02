# v1 Roadmap

What's still unbuilt for v1 (no xG — see README's v2 note for that scope). This is a build plan, not a bug list — see `patch_list.md` for actual fixes to existing code.

## Extraction / derivation

1. **Passing derivation function — DONE.** `passes_completed`/`passes`/`passes_pct` computed from WhoScored raw events (`.isin()` on `Pass`/`BlockedPass`/`OffsidePass`, not a direct `==` match — confirmed via qualifier overlap testing that this correctly captures crosses/through-balls/throw-ins nested inside `qualifiers`, not as separate `type` values).

2. **Possession derivation function — DONE.** Touches by zone, take-ons, from raw events. `carries` remains out of scope for v1 (needs SPADL output format, `output_fmt="spadl"`, not the default event format — never built, deliberately deferred).

3. **Defense derivation function — DONE.** Tackles/interceptions/clearances by zone from raw events. `Challenge`/`dribbled_past` corrected from an initial false win/loss split — confirmed via Opta's own event definitions that `Challenge` is a losing-side-only event, with no corresponding "win" outcome on that same event type.

4. **Final-third/penalty-area entry proxy — DONE.** Zone-geometry check on `end_x`/`end_y` from completed `Pass` events. Serves as the SCA/GCA substitute for v1 (true SCA chain-attribution deferred, not planned for v1 at all). Carries-based entries out of scope, same as item 2.

5. **WhoScored season-scale batch extraction — DONE and verified for 2020-21 through 2025-26. Historical coverage mapped for 2010-11 through 2019-20 (2026-09-01).** `pipelines/whoscored/scrape_all_whoscored_matches.py` ran all four derivation functions above against every match in each season, dumping per-match JSON to `data/whoscored/{season}/`. Enabled by the `force_cache=True` fix (see `patch_list.md`) — without it this would have taken 10-20+ hours/season; with it, real runs completed at ~20s/match.
   - **2020-21 through 2025-26: clean.** 2025-26/2024-25 each had 3 missing (playoff matches, see below); 2022-23 had 6 (3 separate two-legged playoff ties, confirmed via consecutive-pair ID pattern); 2020-21 and 2021-22 had 0 missing. All verified via `tests/whoscored/verify_whoscored_batch.py`, structurally valid, no malformed data. 2025-26 additionally hand spot-checked (most/least-active matches) against the goalkeeper-touch-distribution sanity pattern that caught a real bug earlier — held up correctly.
   - **Playoff matches (2-6 per season depending on how many promotion/relegation ties occurred that year) are consistently excluded** — confirmed via WhoScored's own separate "Eredivisie ECL Playoff" stage categorization, and via the fixed regular-season count (always exactly 306) holding steady while only the variable playoff count changed. Out of scope for this project's regular-season thesis anyway.
   - **2019-20: deliberately lighter, NOT a bug.** 197/250 matches succeeded. The season was suspended 12 March 2020 and formally annulled by the KNVB 24 April 2020 due to COVID-19, after each club had played ~25 of 34 scheduled matches — no champion, no promotion/relegation that year. The 53 "missing" matches never happened in real life; confirmed via external search.
   - **2015-16 through 2018-19: real data exists, but needs a different parser than the one built so far.** soccerdata's standard `read_events()` path crashes (`TypeError: cannot safely cast non-equivalent object to int64`) on how these seasons represent `related_event_id`. Confirmed via `output_fmt="raw"` that real event data genuinely exists (e.g. 1,412 real events recovered from a 2015-16 match) — `tests/whoscored/parse_raw_whoscored_events.py` is a working converter, built and tested, that bypasses the broken casting step. **Not yet integrated into the batch scraper as a fallback** — see item 6 below.
   - **2010-11 through 2014-15: likely mostly genuine data gaps on WhoScored's own side, not yet exhaustively confirmed.** One specific 2010-11 match checked directly via `output_fmt="raw"` came back completely empty (WhoScored's own log: `"No events found for game 409048"`) — a real absence, not a formatting failure. Only one match verified this way so far; the full extent across these 5 seasons is inferred from that single data point, not confirmed match-by-match.

6. **WhoScored data — not yet loaded into Postgres. Fallback parser for 2015-16 through 2018-19 also not yet integrated.** Extraction/verification is done for 2020-21 onward (item 5); no schema or loading script exists yet for the per-match JSON output. Aggregation to player-season totals (summing across a player's ~30+ matches in a season) also not yet built — everything so far is per-match, not per-season. Separately: `parse_raw_whoscored_events.py` (item 5) works standalone but isn't wired into `scrape_all_whoscored_matches.py` as a fallback when the standard path throws the casting `TypeError` — that integration would let 2015-16 through 2018-19 actually be scraped rather than lost.

7. **Transfermarkt scraper — full pipeline complete, in Postgres (2026-08-29/30).** All 29 clubs scraped, filtered against `eredivisie_club_status`, and loaded into `eredivisie_transfers` via `pipelines/transfermarkt/load_eredivisie_transfers.py` — confirmed 8,060 rows inserted, matches `SELECT COUNT(*)` exactly. Still not built: market value *history* (not just current snapshot), bio/injury data.

8. **Loan buy-option/obligation-to-buy data point — not captured, needs its own source. Reconfirmed out of scope for now (2026-08-30).** Confirmed real gap: whether a loan carries a buy-option or obligation-to-buy clause isn't encoded anywhere in the scraped transfer-history data (e.g. Arokodare's loan to Wolves shows plain "loan transfer" despite genuinely including an option to buy). `fee_type` already distinguishes permanent vs. loan vs. paid/unpaid loan — that part is done. The specific option/obligation distinction is a different, unbuilt data source: likely each player's individual transfer-detail page (not the club-level page already scraped), probably reported in prose rather than a structured field, and possibly undisclosed for many transfers regardless. Re-raised and re-declined tonight rather than investigated further, to avoid opening new unconfirmed-structure scraping work this late in a session. Do not infer "no option/obligation" from a loan's current fee_type — this dimension simply isn't in the data at all, not false.

9. **soccerdata (FBref) player-season stats — loaded into Postgres, both known-bad rows fixed and verified (2026-08-30). CLOSED.** `pipelines/soccerdata/load_eredivisie_player_stats.py` loaded all 16 seasons into `eredivisie_player_season_stats`/`eredivisie_keeper_season_stats`. Two intermediate conclusions in this file were wrong and got corrected in sequence -- keeping the trail since it's a real example of verifying rather than assuming:
   - First assumed: exact duplicate source rows, harmless. Wrong -- the two rows per player had different stat values.
   - Second assumed (from the differing values alone): two different real people sharing a name. Wrong -- assumed too fast from internal data disagreement without checking real-world facts.
   - **Verified via external search (Wikipedia, worldfootball.net, FBref's own current player pages, Soccerway): both are ONE real person each, with FBref's own data containing a genuine erroneous duplicate row.** Ricardo Ippel (real DOB 31 Aug 1990, Willem II 2010-2015) -- one row had a wrong born/age (1991/22). Bilal Bayazit (real DOB 8 Apr 1999, Dutch GK, Vitesse 2017-2021) -- one row wrongly listed him as an Icelandic defender. Not a name-collision risk for entity resolution generally -- an isolated FBref data-quality glitch on these 2 specific rows.
   - **Fixed (2026-08-30) via `tests/soccerdata/fix_duplicate_player_rows.py`**: additive counting stats (matches played, minutes, starts, sub appearances) summed across both source rows per player; identity fields (nation/position/born) set to the externally-verified real values; rate stats recomputed from the merged totals. Both `UPDATE`s confirmed 1 row affected each. Final numbers make sense: Ippel 8 MP/151 min/8 sub appearances/18 unused subs (real rotation-player profile); Bayazit 0 MP/0 min/7 unused subs (matches his real career as Vitesse's backup keeper that era). Table count correctly remains 9,229 (a content fix to 2 existing rows, not 2 additions). `(player_name, team, season_id)` kept as the unique key, unchanged.

10. **Entity resolution across sources — can begin now, both major sources loaded and clean.** FBref/soccerdata has NO numeric player ID (name + team + season only); Transfermarkt's `spieler/{id}` is a confirmed clean join key. Cross-source matching will need fuzzy name matching on the soccerdata side, not a clean ID join. Flagged early as likely the single biggest time sink — budget accordingly. Item 9's data-quality issue is resolved and isn't a blocker.

## Infrastructure

11. **Postgres schema — Transfermarkt and soccerdata tables both done and loaded.** `eredivisie_transfers` (8,060 rows), `eredivisie_club_status` (288 rows), `eredivisie_player_season_stats` (9,229 rows), `eredivisie_keeper_season_stats` (589 rows). WhoScored-derived schema still not designed — extraction is done (item 5) but not yet loaded into Postgres (item 6).

12. **tests/ and scripts/ folder reorg — done.**

13. **.gitignore model-artifact lines** — currently ignores models/*.pkl and models/*.joblib by default. Revisit once a first working model exists — decide then whether to commit a baseline model or keep ignoring.

## Not yet started at all

- Docker/FastAPI build
- Azure deployment
- Power BI connection
- Model training itself (XGBoost baseline, SHAP analysis)

## Reference findings (not action items, just context worth keeping)

- Confirmed FBref's Opta-sourced advanced stats (passing/passing_types/goal_shot_creation/defense/possession/keeper_adv) are unavailable — retroactively, across all tested seasons (current, 2025-26, 2021-22) — due to a January 2026 provider license termination. Not a scraper bug, not fixable.
- Checked and ruled out FootyStats and FotMob as scrape targets — both have explicit anti-scraping clauses in their Terms of Service.
- Checked and ruled out worldfootballR's FotMob support (dropped years ago per its own changelog) and the package itself (now unmaintained) as a data source.
- **`counterparty_club_name: "Unknown"` does NOT reliably mean a defunct/folded club.** Confirmed via a real example: Marquinho's 2004 departure from PSV shows `"Unknown"`, but the actual destination (Alianza Lima, Peru) is a real, currently-existing club — Transfermarkt simply has no linked club reference for that specific transfer. Treat `"Unknown"` as "Transfermarkt has a data gap here," not as a signal about the club's real-world status. Identifying the true counterparty for any of these rows requires independent research per row, not something inferable from the scraped data itself.
