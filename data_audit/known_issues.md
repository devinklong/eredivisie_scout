# Known issues

Every EXPLAINED gap, structural limitation, or anomaly found across
this project's history, consolidated in one place. Check here before
treating a coverage gap or outlier as a new, uninvestigated bug --
most likely it's one of these.

Full investigation detail for each lives in `docs/patch_list.md` and
`docs/v1_roadmap.md` -- this file is the short-reference version,
written for someone who needs the answer fast, not the full story.

## Structural (affects many players/teams, by design or by source limitation)

- **`gk_*` columns are NULL for every non-goalkeeper.** Not a gap --
  those stats structurally don't apply to outfield players. Real
  signal for "is this a keeper": `fbref_position LIKE '%GK%'`
  (confirmed real via `master_players_testing.sql` Section 9a, not
  assumed).
- **No WhoScored coverage before the 2013-14 season.** `ws_*` columns
  are correctly NULL for every 2010-2012 row -- WhoScored simply has
  no data that far back for this league.
- **~30-45% baseline WhoScored crosswalk coverage gap, EVERY season,
  2013-2025 -- confirmed structural, not a bug.** A 2020/2021 control
  check (chosen specifically because it's outside any known problem
  window) showed the same ~30-45% gap as everywhere else, ruling out
  a season-specific cause. This is a real, permanent limitation of
  matching FBref's player population against WhoScored's.
- **`passing`/`possession`/`defense`/`GCA` FBref stat types are
  unavailable sitewide, for every season, since a January 2026 Opta
  license termination.** Not scraper-specific -- confirmed via direct
  inspection of soccerdata's raw output. This is why this project's
  advanced-stat coverage leans on WhoScored-derived reconstructions
  instead (`derive_passing_stats.py` etc.) rather than FBref's own
  versions of these categories.
- **FBref itself has no `minutes_per_start`, `substitute_appearances`-
  linked fields, `points_per_match`, `team_goals_while_on_pitch`/
  `_against`, `plus_minus`, `on_off`, `goals`, or `penalty_attempts`
  data for roughly 2010-2017.** Investigated and confirmed a genuine
  FBref historical gap, not a loader bug (closed 2026-09-20).

## Season-specific

- **2019-20: season suspended by the KNVB on 2020-03-12, formally
  annulled 2020-04-24 (COVID-19).** 18 scheduled matches genuinely
  never happened (confirmed via WhoScored's own `status`/`stage`
  fields and match dates falling exactly in the suspension window) --
  a real, permanent gap for that season, not missing data to chase.
  (An earlier, less precise figure of "53 missing" for this season was
  corrected to 18 on 2026-09-16 -- the other 35 were real, recoverable
  matches that later reprocessing picked up.)
- **2016-17 and 2017-18: FBref's own `shots`/`shots_on_target`/
  `shots_on_target_pct` were a literal `0`, not `NULL`, at the
  source.** Confirmed via direct inspection of soccerdata's raw
  output, bypassing this project's own code -- genuine FBref-side data
  gap for these two seasons specifically. Fixed via a WhoScored-derived
  reconstruction (`derive_shots_stats.py`,
  `fix_shots_with_whoscored_derivation.sql`) -- validated end-to-end
  as of 2026-09-19 (6,474 real rows, 0 `shots_on_target > shots`
  violations).
- **2025-26's WhoScored schedule includes 3 promotion/relegation
  playoff matches** (involving non-Eredivisie Eerste Divisie clubs) --
  correctly excluded, not a scraping failure. 306/309 real
  regular-season matches is the complete, correct result for that
  season.

## Player-specific identity fixes (already resolved, not open issues)

- **Marcus Pedersen**: two genuinely different real people share this
  name -- a striker (born 1990, Vitesse/Strømsgodset/Brann career,
  `player_id 271`) and a defender, full name Marcus Holmgren Pedersen
  (born 2000, Feyenoord/Torino career, `player_id 999`). Split via
  `canonical_born`/`canonical_whoscored_player_id` disambiguators.
  Confirmed via external verification (Wikipedia, FotMob) that both
  are real, distinct players, not a false duplicate.
- **Eric Botteghin**: one real person, two WhoScored name spellings
  ("Eric Botteghin" / "Eric Fernando Botteghin") -- caused a
  season-split bug in the raw WhoScored aggregation. Fixed both the
  specific data and the aggregation script's root logic (keys by
  `whoscored_player_id` now, not name string).
- **`player_id 1711`**: an orphaned duplicate of Marcus Holmgren
  Pedersen (`999`) with zero `player_source_crosswalk` entries --
  inert (could never join to real stats), predated this session
  (created 2026-09-10), confirmed isolated, deleted 2026-09-20.

## Team-naming (resolved, not open issues)

- FBref, WhoScored, and Transfermarkt each use their own naming
  convention for several clubs (e.g. `"Groningen"` vs.
  `"FC Groningen"`, `"PEC Zwolle"` vs. `"Zwolle"`, `"Sparta"` vs.
  `"Sparta Rotterdam"` vs. `"Sparta R."`). Resolved via
  `team_name_alias`, a closed 29-club lookup table anchored on
  Transfermarkt's numeric `club_id` -- every join across sources now
  goes through `team_id`, not a raw name string. Confirmed complete
  (gap report returns zero unmapped names) as of 2026-09-16.

## Bio data

- **`height_cm`/`foot` genuinely absent for some players** -- Confirmed
  real Transfermarkt-side gap for lower-profile/youth players, not a
  scraping failure (per the schema's own long-standing documentation).
- **Two implausible `height_cm = 875` rows** (player_ids `101810`,
  `128168`) -- a decimal-parsing artifact, fixed 2026-09-20 by
  deleting the rows so `scrape_player_bio.py` naturally re-fetches
  real values on its next run.

## Outlier-detection methodology limitations (known, not bugs in the data)

- **`flag_outliers.py`'s z-score baseline blends all positions together
  for every column -- any stat that's inherently position-specific
  will keep getting flagged as an "outlier" every run, regardless of
  minutes floor or z-threshold, because the comparison population
  includes positions the stat doesn't apply evenly to. Confirmed
  across FOUR separate stat families as of 2026-09-23, not a one-off
  -- treat any newly-flagged column as a likely next instance before
  assuming it's a real anomaly.**
  - `ws_touches_def_pen_area`: 31/31 flagged rows are `GK` --
    structurally, not statistically, unusual (matches the sanity check
    already documented in `derive_possession_stats.py`'s own
    docstring: goalkeepers legitimately dominate this zone).
  - `ws_aerials`/`ws_aerials_won`/`ws_aerials_per90`/
    `ws_aerials_won_per90`: 42/46 flagged rows are `FW` -- genuine
    elite aerial performers (target forwards), not a keeper-driven
    artifact like the touches case, but the same root cause: a
    blended-position baseline makes any position-concentrated stat
    look extreme.
  - `ws_errors`/`ws_errors_per90`: 26/27 flagged rows are `GK` or `DF`
    -- matches the football-logical expectation that a WhoScored
    "error" (a mistake directly leading to a shot/goal) concentrates
    among the players closest to danger, not attackers or midfielders.
  - `ws_tackles*`/`ws_interceptions*` zone variants
    (`_att_3rd`/`_mid_3rd`/`_def_3rd` and their `_per90` forms) plus
    `ws_clearances`: a ZONE-MATCHED-TO-ROLE version of the same
    pattern, confirmed 2026-09-23 -- `MF` dominates the `_att_3rd`/
    `_mid_3rd` variants (pressing/midfield actions), `DF` dominates
    `_def_3rd` variants and `clearances` (own-box defending). Same
    root cause as the others, just manifesting zone-by-zone rather
    than as one dominant position across a whole column.
  - Real fix, not yet built: the baseline should be computed
    per-position (or at minimum GK vs. outfield) for any column known
    to cluster by role, rather than one mean across the whole season.
    Until that's built, expect this same shape of flag to recur every
    time `flag_outliers.py` is re-run, for these specific columns and
    likely others sharing the same position-concentration pattern
    (candidates worth checking first if they show up flagged again:
    anything zone-based like `touches_att_3rd`/`def_3rd`, or role-based
    like `tackles`/`interceptions` by zone).

- **`fbref_on_off` has a near-zero season mean/stddev, making its
  z-score hypersensitive -- nearly any nonzero value reads as
  "extreme" regardless of real magnitude.** Confirmed 2026-09-23: the
  8 flagged rows mixed genuine stars (Tadić, Reijnders) with unknown
  players (Peters, Fischer, Röseler) at similarly wild z-scores
  (11-14) -- a metric-scaling issue, not 8 individual football
  stories. Not yet fixed (would need a different outlier-detection
  approach for near-zero-variance columns specifically, not the
  season-mean z-score used everywhere else).

- **`fbref_minutes_per_sub` has no floor on the number of substitute
  appearances behind it.** A player with only 1-2 sub appearances can
  show an extreme-looking per-appearance rate off a genuinely tiny
  sample -- same root cause as the original `fbref_nineties` floor
  gap, just a different denominator that floor doesn't cover. Not yet
  fixed in `flag_outliers.py` as of 2026-09-23.

## Loader bugs found and fixed

- **`fbref_goals`/`fbref_penalty_attempts` were 100% NULL across ALL 16
  seasons, not just the documented 2010-2017 range -- found 2026-09-28
  via the coverage audit's `pct_populated = 0` check.** Root cause:
  `load_eredivisie_player_stats.py` looked up `Performance_Gls_std`/
  `Performance_PKatt_std`, but real soccerdata output for these two
  columns has no `_std` suffix (confirmed via direct inspection) --
  same class of bug as the earlier `own_club_name`/table-rename
  issues, a guessed key that was never verified against real output.
  Fixed in the loader (permanent fix for future loads) and backfilled
  via a targeted `UPDATE` script for the 9,229 existing rows (no full
  reload needed, since `ON CONFLICT DO NOTHING` would have skipped
  every already-existing row anyway).
  - **After the fix, ~55-95 rows per season (2014 onward) still show
    `goals IS NULL` -- confirmed benign, not a residual bug.** These
    are players with `position`/`age` populated but `minutes`/`goals`/
    `assists`/`shots` all NULL together, as a complete block -- mostly
    teenage squad/reserve players and backup goalkeepers. They never
    had a real `standard`-stat_type row at all; `fetch_season_player_
    stats()`'s `outer` join means a player present in only one of the
    four merged stat types (e.g. `misc` or `playing_time`) still gets
    a row, with every `standard`-sourced column (goals included)
    correctly NULL. Not something to chase further -- flagging here so
    a future audit doesn't mistake it for a new bug. 2010-2013 shows
    NO such gap (has_goals = total exactly) -- worth knowing if the
    exact row-count-vs-season pattern ever needs re-deriving.

## Real, confirmed gaps -- scoped, but not yet fixed

- **A THIRD genuine FBref historical gap, confirmed 2026-09-29: the entire `misc` and `keeper` stat types return completely empty (`<NA>`) for the 2018-19 season specifically, at FBref's own source -- not a loader bug.** Found via `data_audit/build_team_season_summary.py`'s team/season rollup, which surfaced a clean discontinuity for exactly one season (2017: ~57-81% depending on column, 2018: exactly 0.0% across every affected column, 2019: back to ~41-79%) across MANY teams simultaneously -- the shape that distinguishes a real source-side gap from a team-specific data problem. An earlier read of this data (an AZ-specific 56.4%/60.9% dip flagged as worth investigating) turned out to be a symptom of this same league-wide gap, not an AZ-specific issue -- worth remembering that a team's rollup number can look team-specific while the real cause is season-wide.

  Confirmed via the same direct-inspection method that resolved the original 2016-17/2017-18 shots gap: `soccerdata`'s raw `misc` stat-type pull for 2018-19 returns a real DataFrame (479 rows, correct 17 columns, correct column name `Performance_Fls`) but every value is `<NA>` -- ruling out a wrong-column-key bug like the `goals`/`penalty_attempts` fix earlier tonight. Same confirmed for `keeper` (37 real rows, correct `Performance_Saves` column name, all `<NA>`).

  **Affected columns**: everything sourced from `misc` (`fbref_fouls_committed`, `fbref_fouls_drawn`, `fbref_offsides`, `fbref_crosses`, `fbref_interceptions`, `fbref_tackles_won`, and likely a few others from that same stat type not yet individually spot-checked) and everything from `keeper` (`gk_saves`, `gk_save_pct`, `gk_shots_on_target_against`, and likely the rest of that stat type) -- for season 2018 (2018-19) ONLY. Confirmed via direct season-by-season query that 2017 and 2019 are both genuinely populated -- this is not bleeding into neighboring seasons.

  **NOT YET FIXED.** Given the diagnosis matches the already-solved `shots` gap exactly (genuinely empty at FBref's source, confirmed by bypassing this project's own loading code), the established precedent is a WhoScored-derived reconstruction, same approach as `derive_shots_stats.py`. For `misc`'s columns, this is likely straightforward -- `derive_defense_stats.py` and similar already produce comparable stats (fouls, interceptions, tackles) from WhoScored raw events for the `ws_*` columns elsewhere in `master_player_season_stats`, so the derivation logic may already exist and just needs pointing at this specific gap. For `keeper`'s columns, no WhoScored-derived keeper reconstruction (`derive_keeper_stats.py` or equivalent) exists in this project yet -- would need to be built from scratch, the same real iteration process the original shots definition required (multiple attempts, real validation against known-good seasons) before it could be trusted. Scoped as its own dedicated session, not a quick fix -- deliberately not rushed into tonight.

## Not yet investigated (genuinely open, not yet explained)

- Whether `foot`'s ~25% NULL rate specifically is fully explained by
  "Transfermarkt doesn't have it" or has some other component --
  never separately confirmed, just assumed consistent with the
  already-documented height gap.
- Anything the season/team/player coverage matrices in this folder
  surface that isn't already listed above -- add it here once
  explained, following this file's format.
