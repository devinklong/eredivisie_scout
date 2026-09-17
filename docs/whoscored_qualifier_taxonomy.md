# WhoScored Qualifier Taxonomy

How each WhoScored/Opta qualifier tag is treated when deriving player-season stats from raw events. Built empirically (via `tests/whoscored/check_qualifier_overlap.py`), not assumed — see the "confirmed via" note on each group.

Two possible treatments:
- **Categorical (single column)** — tags in the group are mutually exclusive (or rare enough overlap to collapse safely). Aggregated as one column, counted/percentaged per category.
- **Independent flags (stacking)** — tags in the group can co-occur on the same event. Each gets its own boolean column, aggregated as an independent sum. Treating these as categorical would silently lose information.

## Passing — confirmed 2026-08-27, game_id=1982244 (875 Pass events)

### Technique — INDEPENDENT FLAGS (not categorical — initial assumption was wrong)
Tags: `Cross`, `Chipped`, `HeadPass`, `LayOff`, `Longball`, `Throughball`

Confirmed via overlap check: 75/875 passes (8.6%) carried 2+ technique tags at once. Most common: `Chipped`+`Longball` (56), `Chipped`+`Cross` (23), `Cross`+`Longball` (12). These are real, coherent combinations (e.g. a chipped long ball), not tagging noise — collapsing to one column would force an arbitrary pick and lose real signal.

→ Build as: `is_cross`, `is_chipped`, `is_headpass`, `is_longball`, `is_layoff`, `is_throughball` (one boolean column each).

### Restart context — CATEGORICAL (single column)
Tags: `CornerTaken`, `FromCorner`, `FreekickTaken`, `IndirectFreekickTaken`, `ThrowIn`

Confirmed via overlap check: only 3/875 passes showed overlap, and the pairs found (`FreekickTaken`+`IndirectFreekickTaken`, `CornerTaken`+`FromCorner`) are compatible descriptions of the same restart type, not contradictions.

→ Build as: one `restart_type` categorical column (`open_play` as the default when none of these tags present).

### Outcome — INDEPENDENT FLAGS (stacking, as expected)
Tags: `KeyPass`, `ShotAssist`, `IntentionalAssist`, `IntentionalGoalAssist`, `BigChanceCreated`

Confirmed via overlap check: 25/875 passes (2.9%) carried multiple outcome tags — e.g. `KeyPass`+`ShotAssist` together 25 times, with `BigChanceCreated`/`IntentionalGoalAssist` layering on the best chances. These describe independent facts about the same pass and are expected to stack.

→ Build as: `is_key_pass`, `is_shot_assist`, `is_intentional_assist`, `is_goal_assist`, `is_big_chance_created` (one boolean column each).

### Foot — CATEGORICAL (single column / rate)
Tags: `LeftFoot`, `RightFoot`

Not yet empirically overlap-tested (assumed mutually exclusive — a pass is played with one foot). Worth running the same overlap check before treating this as settled.

→ Build as: `pct_passes_left_foot` (rate, not a raw count).

### Numeric fields — NOT counted, aggregated as averages
`Angle`, `Length`, `Zone` — confirmed (via external Opta qualifier reference, not yet directly verified in our own data) to be numeric/positional values, not category tags. `PassEndX`/`PassEndY` confirmed redundant with the `end_x`/`end_y` columns already present directly on each event row (verified exact match: 18.5, 48.5 both places) — do not parse these from `qualifiers` at all, use the existing columns.

→ `Length` → `avg_pass_length`. `Angle` → possibly `avg_pass_angle` or bucketed direction, TBD. `Zone` → Opta's own pitch-zone label, categorical, not yet used in any feature.

### Unresolved — do not use until definition confirmed
`MissHigh`, `Offensive` — no confirmed definition found (checked external Opta qualifier references, inconclusive). `MissHigh` in particular may be a shot-event artifact appearing on pass rows due to how soccerdata flattens `qualifiers`, not a genuine pass descriptor. Do not build features from these until verified.

## Cross-event relationships

Some WhoScored/Opta event types only make sense in relation to a *different* event type on the opposing player — the "win" and "loss" sides of the same real-world moment are logged as two separate event types, not one event with an outcome flag. Confirmed via Opta's own event definitions (optasports.com/news/optas-event-definitions, statsperform.com/opta-event-definitions). Building any true win/loss or "duel" style stat requires deliberately joining these pairs — pulling one event type alone will silently give you only one side of the story (see: the `Challenge` bug, 2026-08-28, where every player showed 0 wins because the win event doesn't exist under that type at all).

| Event type (loss/attempt side) | Paired event type (win side) | Relationship |
|---|---|---|
| `Challenge` | `TakeOn` (opponent, Successful) | Defender's Challenge is always a loss; the dribbler's successful TakeOn is the corresponding win. Two different players' events. |
| `Tackle` (outcome unsuccessful) or none | `TakeOn` (Successful) / `Dispossessed` (opponent) | A tackle attempt that fails may show up as the attacker's successful TakeOn instead. |
| `Aerial` | `Aerial` (opponent, opposite outcome_type) | **CONFIRMED (2026-09-13), no longer just assumed:** Aerial duels DO carry their own win/loss outcome directly on the same event type — this is the one pair that doesn't require cross-referencing a different type, matching `Tackle`'s pattern rather than `Challenge`'s. Verified via `pipelines/whoscored/check_aerial_outcome.py` against real data (game_id=1982244): 56 Aerial events, `outcome_type` split exactly 28 `Successful` / 28 `Unsuccessful` — a clean 50/50 split, the expected signature of a properly paired win/loss event type. `derive_aerial_stats.py` built on the strength of this confirmation. |
| `Foul` (won) | `Foul` (conceded, opponent) | **CONFIRMED (2026-09-16):** same pattern as Aerial — Foul carries its own win/loss outcome directly, no cross-referencing needed. Verified via `pipelines/whoscored/check_foul_outcome.py` against real data (game_id=1982244, current 2026-27 season): 34 Foul events, `outcome_type` split exactly 17 `Successful` / 17 `Unsuccessful` — the same clean 50/50 signature as Aerial. Safe to build a win-rate feature directly off `outcome_type` without joining against a separate event type. |

**`SavedShot`'s own qualifiers distinguish a genuine on-target attempt from a blocked one — CONFIRMED (2026-09-14).** Opta's own published "shots on target" definition explicitly includes shots blocked by a last-man defender, not just genuine goalkeeper saves — meaning `SavedShot` alone conflates two different things. Checked real qualifier data (17 sampled `SavedShot` events, `pipelines/whoscored/check_savedshot_qualifiers.py`): events split cleanly into two groups agreeing with each other on two independent signals in 16 of 17 cases — an explicit `Blocked` qualifier tag with no `GoalMouthY`/`GoalMouthZ` coordinates (the shot's trajectory was never tracked to the goal frame, because it was stopped first), vs. real `GoalMouthY`/`GoalMouthZ` coordinates with no `Blocked` tag (a genuine attempt tracked all the way to the goal). This project deliberately uses the narrower "reached the goal frame or scored" convention for `shots_on_target` (see `derive_shots_stats.py` and `docs/v1_roadmap.md` for the full reasoning), not Opta's own broader one.

**`BlockedPass` attribution — CHECKED (2026-09-16), stays unresolved, and now for a more specific reason than "not yet checked."** `related_player_id` is empty on 100% of sampled `BlockedPass` events (0/7), and the dedicated `related_event_id` column is entirely `NaN` for this event type too — neither structured field is populated. The `OppositeRelatedEvent` qualifier tag *does* carry a numeric value on every sampled event, and initially looked promising: cross-referencing it against the match's event log correctly resolved to the opposing team's blocked `Pass` event, at the same minute, in 4 of 7 sampled cases. But the other 3/7 resolved to nonsense — same team as the blocker, several minutes off, wrong event type (`Interception`, `BallRecovery`), one even pointing back to the *same player* who made the block. Root cause found: **`event_id` is not a unique key in this data** — 621 duplicate `event_id` values out of 1425 total events in the sampled match (game_id=1982244), not just a per-period reset (duplicate pairs span the same half at different minutes). A bare `event_id == X` lookup against `OppositeRelatedEvent`'s value is therefore unreliable by construction, not by chance — the 4/7 "correct" results happened to land on the right row among duplicates, the other 3/7 didn't. Building a disambiguation heuristic (e.g. nearest-in-time + opposite-team) to work around this would mean guessing at attribution, not verifying it, which this project's own standard rules out. **Do not build a `BlockedPass` attribution feature.**

**Still unmapped / not yet checked:** none remaining in this category as of 2026-09-16 — `Foul` and `BlockedPass` (above) were the last two open items.
