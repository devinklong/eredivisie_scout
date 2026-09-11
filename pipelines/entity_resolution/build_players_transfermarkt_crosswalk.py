"""
Adds confirmed Transfermarkt links to the EXISTING player_source_crosswalk
-- never creates new players rows, unlike build_players_crosswalk.py.
Every candidate pair here already carries a real canonical_player_id
(from the players table), since players_transfermarkt_candidate_pairs
starts from `players p` and joins outward -- so this loader only ever
attaches a source='transfermarkt' crosswalk row to a player who already
exists, it doesn't need the create-a-new-player branch the FBref/
WhoScored loader needed.

Confirmed matches come from TWO inputs, same pattern as before:
  1. Exact-normalized matches (working_confidence == 1.0) from
     players_transfermarkt_candidates.csv.
  2. Manually-reviewed matches (decision == 'match') from
     players_transfermarkt_review_queue.csv.

The 20 "high confidence, not exact" (0.8-1.0) candidates are
DELIBERATELY EXCLUDED, same reasoning as before -- not yet individually
reviewed.

CONTRADICTION CHECKING, BOTH DIRECTIONS -- a genuine addition over
build_players_crosswalk.py, which only needed to check one direction
(since it was building canonical identity from scratch). This script
attaches a THIRD source to identities already fixed by the first
match, so two new failure modes are possible and both are checked:
  (a) one canonical_player_id confirmed matching two DIFFERENT
      transfermarkt_player_ids (same shape as the Eric Botteghin case,
      but here it might mean the SAME real person has two Transfermarkt
      profiles, or it might mean one of the confirmed pairs is wrong --
      unlike Eric Botteghin, this is NOT auto-resolved, since we don't
      have independent verification either way -- flagged and skipped).
  (b) one transfermarkt_player_id confirmed matching two DIFFERENT
      canonical_player_ids -- this would mean two canonical players
      (already established as different real people via the FBref/
      WhoScored match) are both claiming the same real Transfermarkt
      identity. This is a genuinely new risk this second pass
      introduces -- flagged and skipped, not guessed at.

Requires source_native_id to already exist on player_source_crosswalk
-- run add_source_native_id_column.sql FIRST.
"""

from pathlib import Path

import pandas as pd
import psycopg2

CANDIDATES_FILE = Path("cleaning_logs/entity_resolution/players_transfermarkt_candidates.csv")
REVIEW_QUEUE_FILE = Path("cleaning_logs/entity_resolution/players_transfermarkt_review_queue.csv")


def get_connection():
    return psycopg2.connect(dbname="postgres", host="localhost")


def load_exact_matches():
    df = pd.read_csv(CANDIDATES_FILE)
    exact = df[df["working_confidence"] == 1.0]
    deduped = exact.drop_duplicates(subset=["canonical_player_id", "transfermarkt_player_id"])

    pairs = []
    for _, row in deduped.iterrows():
        pairs.append({
            "canonical_player_id": row["canonical_player_id"],
            "transfermarkt_player_id": row["transfermarkt_player_id"],
            "transfermarkt_name": row["transfermarkt_name"],
            "confidence": row["working_confidence"],
            "match_method": "exact_normalized",
            "verified": False,
            "notes": None,
        })
    return pairs


def load_reviewed_matches():
    df = pd.read_csv(REVIEW_QUEUE_FILE)
    df["decision_normalized"] = df["decision"].astype(str).str.strip().str.lower()
    matched = df[df["decision_normalized"] == "match"]
    deduped = matched.drop_duplicates(subset=["canonical_player_id", "transfermarkt_player_id"])

    pairs = []
    for _, row in deduped.iterrows():
        notes = row.get("notes")
        pairs.append({
            "canonical_player_id": row["canonical_player_id"],
            "transfermarkt_player_id": row["transfermarkt_player_id"],
            "transfermarkt_name": row["transfermarkt_name"],
            "confidence": row["working_confidence"],
            "match_method": "manual_review",
            "verified": True,
            "notes": notes if pd.notna(notes) and str(notes).strip() else None,
        })
    return pairs


def check_for_contradictions(pairs):
    """Checks BOTH directions -- see module docstring. Returns
    (skip_canonical_ids, skip_transfermarkt_ids)."""
    canonical_to_tm = {}
    tm_to_canonical = {}
    for p in pairs:
        canonical_to_tm.setdefault(p["canonical_player_id"], set()).add(p["transfermarkt_player_id"])
        tm_to_canonical.setdefault(p["transfermarkt_player_id"], set()).add(p["canonical_player_id"])

    canonical_contradictions = {k: v for k, v in canonical_to_tm.items() if len(v) > 1}
    tm_contradictions = {k: v for k, v in tm_to_canonical.items() if len(v) > 1}

    if canonical_contradictions:
        print(f"WARNING: {len(canonical_contradictions)} canonical_player_id(s) matched to "
              f"multiple different transfermarkt_player_ids -- SKIPPING these:")
        for cid, tm_ids in canonical_contradictions.items():
            print(f"  canonical_player_id={cid} -> transfermarkt_player_ids={sorted(tm_ids)}")

    if tm_contradictions:
        print(f"WARNING: {len(tm_contradictions)} transfermarkt_player_id(s) matched to "
              f"multiple different canonical_player_ids -- SKIPPING these:")
        for tm_id, cids in tm_contradictions.items():
            print(f"  transfermarkt_player_id={tm_id} -> canonical_player_ids={sorted(cids)}")

    return set(canonical_contradictions.keys()), set(tm_contradictions.keys())


INSERT_SQL = """
    INSERT INTO player_source_crosswalk
        (player_id, source, source_name, source_native_id, confidence, match_method, verified, notes)
    VALUES (%s, 'transfermarkt', %s, %s, %s, %s, %s, %s)
    ON CONFLICT (player_id, source, source_name) DO NOTHING
"""


def main():
    exact_pairs = load_exact_matches()
    reviewed_pairs = load_reviewed_matches()
    print(f"{len(exact_pairs)} exact-normalized pairs, "
          f"{len(reviewed_pairs)} manually-reviewed 'match' pairs.")

    all_pairs = exact_pairs + reviewed_pairs
    skip_canonical_ids, skip_tm_ids = check_for_contradictions(all_pairs)
    all_pairs = [
        p for p in all_pairs
        if p["canonical_player_id"] not in skip_canonical_ids
        and p["transfermarkt_player_id"] not in skip_tm_ids
    ]

    conn = get_connection()
    inserted = 0
    with conn.cursor() as cur:
        for pair in all_pairs:
            cur.execute(INSERT_SQL, (
                pair["canonical_player_id"], pair["transfermarkt_name"],
                pair["transfermarkt_player_id"], pair["confidence"],
                pair["match_method"], pair["verified"], pair["notes"],
            ))
            inserted += cur.rowcount
        conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM player_source_crosswalk WHERE source = 'transfermarkt'")
        total_transfermarkt_rows = cur.fetchone()[0]

    conn.close()

    print(f"\n{inserted} new transfermarkt crosswalk rows inserted this run.")
    print(f"player_source_crosswalk now has {total_transfermarkt_rows} total transfermarkt-source rows.")


if __name__ == "__main__":
    main()
