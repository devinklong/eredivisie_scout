"""
Checks how often qualifier tags actually co-occur on the same Pass event,
rather than assuming mutual-exclusivity vs. stacking based on reasoning
alone. Also checks whether PassEndX/PassEndY (found inside qualifiers)
are redundant with the end_x/end_y columns soccerdata already exposes
directly on each event row.
"""

from itertools import combinations

import soccerdata as sd

LEAGUE = "NED-Eredivisie"
SEASON = "2026-27"
MATCH_ID = 1982244

TECHNIQUE_TAGS = ["Cross", "Chipped", "HeadPass", "LayOff", "Longball", "Throughball"]
RESTART_TAGS = ["CornerTaken", "FromCorner", "FreekickTaken", "IndirectFreekickTaken", "ThrowIn"]
OUTCOME_TAGS = ["KeyPass", "ShotAssist", "IntentionalAssist", "IntentionalGoalAssist", "BigChanceCreated"]


def get_tags(qualifiers):
    if not isinstance(qualifiers, list):
        return set()
    return {q.get("type", {}).get("displayName") for q in qualifiers if q.get("type", {}).get("displayName")}


def check_group_overlap(pass_rows, group_name, tags):
    print(f"\n--- {group_name} ---")
    multi_tag_count = 0
    for qualifiers in pass_rows["qualifiers"]:
        present = get_tags(qualifiers) & set(tags)
        if len(present) > 1:
            multi_tag_count += 1
    print(f"Passes with 2+ tags from this group at once: {multi_tag_count} / {len(pass_rows)}")

    # Show which specific pairs co-occur, if any
    pair_counts = {}
    for qualifiers in pass_rows["qualifiers"]:
        present = sorted(get_tags(qualifiers) & set(tags))
        for pair in combinations(present, 2):
            pair_counts[pair] = pair_counts.get(pair, 0) + 1
    if pair_counts:
        print("Co-occurring pairs found:")
        for pair, count in sorted(pair_counts.items(), key=lambda x: -x[1]):
            print(f"  {pair}: {count}")
    else:
        print("No co-occurring pairs found -- tags in this group are mutually exclusive.")


def check_passendxy_redundancy(pass_rows):
    print("\n--- PassEndX/PassEndY redundancy check ---")
    sample = pass_rows.iloc[0]
    qualifiers = sample.get("qualifiers", [])
    for q in qualifiers:
        name = q.get("type", {}).get("displayName")
        if name in ("PassEndX", "PassEndY"):
            print(f"  Qualifier '{name}' value: {q.get('value')}")
    print(f"  Row's own end_x/end_y columns: {sample.get('end_x')}, {sample.get('end_y')}")


def main():
    ws = sd.WhoScored(LEAGUE, SEASON)
    events = ws.read_events(match_id=MATCH_ID)
    pass_rows = events[events["type"] == "Pass"]

    check_group_overlap(pass_rows, "Technique", TECHNIQUE_TAGS)
    check_group_overlap(pass_rows, "Restart context", RESTART_TAGS)
    check_group_overlap(pass_rows, "Outcome", OUTCOME_TAGS)
    check_passendxy_redundancy(pass_rows)


if __name__ == "__main__":
    main()
