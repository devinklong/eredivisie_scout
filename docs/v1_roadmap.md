# v1 Roadmap

What's still unbuilt for v1 (no xG — see README's v2 note for that scope). This is a build plan, not a bug list — see `patch_list.md` for actual fixes to existing code.

## Extraction / derivation

1. **Passing derivation function** — compute `passes_completed`/`passes`/`passes_pct` and short/medium/long distance bucketing from WhoScored raw events.

2. **Possession derivation function** — touches by zone, take-ons, from raw events. Note: `carries` specifically needs SPADL output format (`output_fmt="spadl"`), not the default event format.

3. **Defense derivation function** — tackles/interceptions/blocks/clearances by zone from raw events.

4. **Final-third/penalty-area entry proxy** — zone-geometry check on `end_x`/`end_y` from passing/carry events. Serves as the SCA/GCA substitute for v1 (true SCA chain-attribution deferred, not planned for v1 at all).

5. **Transfermarkt scraper — squad + recent transfers built (2026-08-29).** `pipelines/transfermarkt/extract_transfermarkt_squad.py` extracts Ajax's squad (player_id, name, position, DOB, market value) and recent transfers (player_id, counterparty club, direction, structured fee with type: permanent/paid_loan/unpaid_loan/free_transfer). Confirmed real player IDs (`spieler/{id}`) usable as an entity-resolution join key. Still not built: applying this across all 18 Eredivisie clubs (currently Ajax-only), market value *history* (not just current snapshot), bio/injury data, and multi-season historical transfers.

6. **Loan buy-option data point — not captured, needs its own source.** Confirmed real gap: whether a loan carries a buy-option clause isn't encoded anywhere in the squad-page fee text (e.g. Arokodare's loan to Wolves shows plain "loan transfer" despite genuinely including an option to buy). Likely only available, if at all, on each player's individual transfer-history page — a different URL, not yet scraped. Do not infer "no option" from an unpaid-loan label.

7. **Entity resolution across sources** — FBref/soccerdata, WhoScored, and Transfermarkt each have their own player IDs and name formats; no cross-source matching logic exists yet. Flagged early as likely the single biggest time sink — budget accordingly. Transfermarkt's `spieler/{id}` is now a confirmed available join key on that side.

## Infrastructure

8. **Postgres schema design** — needs to wait until real column structures from all three sources are settled (soccerdata's is; WhoScored-derived and Transfermarkt's aren't yet).

9. **tests/ and scripts/ folder reorg** — decided (soccerdata/fbref/whoscored/transfermarkt subfolders) but not yet executed against the actual files on disk. Several scripts moved between tests/ and scripts/ over the course of tonight — verify actual current paths before running the git mv commands.

10. **.gitignore model-artifact lines** — currently ignores models/*.pkl and models/*.joblib by default. Revisit once a first working model exists — decide then whether to commit a baseline model or keep ignoring.

## Not yet started at all

- Docker/FastAPI build
- Azure deployment
- Power BI connection
- Model training itself (XGBoost baseline, SHAP analysis)

## Reference findings (not action items, just context worth keeping)

- Confirmed FBref's Opta-sourced advanced stats (passing/passing_types/goal_shot_creation/defense/possession/keeper_adv) are unavailable — retroactively, across all tested seasons (current, 2025-26, 2021-22) — due to a January 2026 provider license termination. Not a scraper bug, not fixable.
- Checked and ruled out FootyStats and FotMob as scrape targets — both have explicit anti-scraping clauses in their Terms of Service.
- Checked and ruled out worldfootballR's FotMob support (dropped years ago per its own changelog) and the package itself (now unmaintained) as a data source.
