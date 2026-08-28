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
`MissHigh`, `Offensive`, `OppositeRelatedEvent` — no confirmed definition found (checked external Opta qualifier references, inconclusive). `MissHigh` in particular may be a shot-event artifact appearing on pass rows due to how soccerdata flattens `qualifiers`, not a genuine pass descriptor. Do not build features from these until verified.
