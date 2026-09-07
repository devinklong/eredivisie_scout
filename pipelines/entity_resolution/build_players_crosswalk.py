"""
Builds the players / player_source_crosswalk tables from confirmed
FBref <-> WhoScored matches, from TWO sources of confirmed identity:

  1. Exact-normalized matches (working_confidence == 1.0) from
     fbref_whoscored_candidates.csv -- these needed no manual review;
     normalization alone gave both names an identical form.
  2. Manually-reviewed matches (decision == 'match') from
     fbref_whoscored_review_queue.csv -- the 0.5-0.8 band that could
     not be resolved by scoring alone (see match_fbref_whoscored.py's
     docstring for why).

The 159 "high confidence, not exact" (0.8-1.0) candidates are
DELIBERATELY EXCLUDED here -- they have not been individually
spot-checked yet (flagged as still-open in docs/v1_roadmap.md), so
loading them now would mean writing unverified links into the
canonical identity table. Revisit once that band has been reviewed,
the same way the 0.5-0.8 band was.

Canonical naming: for every confirmed pair, players.canonical_name
defaults to the FBref-side name (decided 2026-09-07) -- both
exact-normalized and manually-reviewed matches follow this rule
consistently.

IDEMPOTENT: safe to rerun. For each confirmed (fbref_name,
whoscored_name) pair, checks whether a crosswalk row already exists
for the FBref side (source='fbref', source_name=fbref_name) --
if so, reuses that player_id rather than creating a duplicate players
row; if not, creates a new players row first. The WhoScored-side
crosswalk insert uses ON CONFLICT DO NOTHING on the (player_id,
source, source_name) unique constraint, so re-running this script
after a fresh review-queue export does not duplicate anything already
loaded.

Any fbref_name that maps to two DIFFERENT whoscored_names across the
confirmed-match input is a contradiction (two different reviewed pairs
disagreeing about the same person's identity) -- flagged as a warning
and SKIPPED, not silently resolved either way, since guessing which
one is right would be worse than leaving it for a human to sort out.
"""

from pathlib import Path

import pandas as pd
import psycopg2

CANDIDATES_FILE = Path("cleaning_logs/entity_resolution/fbref_whoscored_candidates.csv")
REVIEW_QUEUE_FILE = Path("cleaning_logs/entity_resolution/fbref_whoscored_review_queue.csv")


def get_connection():
    return psycopg2.connect(dbname="postgres", host="localhost")


def load_exact_matches():
    """Exact-normalized matches (working_confidence == 1.0), deduped by
    (fbref_name, whoscored_name) -- collapses the season-by-season
    repeats (e.g. Klaas-Jan Huntelaar appearing once per season at
    Ajax) down to one identity link."""
    df = pd.read_csv(CANDIDATES_FILE)
    exact = df[df["working_confidence"] == 1.0]
    deduped = exact.drop_duplicates(subset=["fbref_name", "whoscored_name"])

    pairs = []
    for _, row in deduped.iterrows():
        pairs.append({
            "fbref_name": row["fbref_name"],
            "whoscored_name": row["whoscored_name"],
            "confidence": row["working_confidence"],
            "match_method": "exact_normalized",
            "verified": False,
            "notes": None,
        })
    return pairs


def load_reviewed_matches():
    """Manually-reviewed matches (decision == 'match', case-insensitive
    and whitespace-tolerant, since the review file was hand-edited in
    a spreadsheet app), deduped by (fbref_name, whoscored_name)."""
    df = pd.read_csv(REVIEW_QUEUE_FILE)
    df["decision_normalized"] = df["decision"].astype(str).str.strip().str.lower()
    matched = df[df["decision_normalized"] == "match"]
    deduped = matched.drop_duplicates(subset=["fbref_name", "whoscored_name"])

    pairs = []
    for _, row in deduped.iterrows():
        notes = row.get("notes")
        pairs.append({
            "fbref_name": row["fbref_name"],
            "whoscored_name": row["whoscored_name"],
            "confidence": row["working_confidence"],
            "match_method": "manual_review",
            "verified": True,
            "notes": notes if pd.notna(notes) and str(notes).strip() else None,
        })
    return pairs


def check_for_contradictions(pairs):
    """A contradiction: the same fbref_name confirmed as matching two
    DIFFERENT whoscored_names. Flags and returns the list of
    fbref_names to skip, rather than guessing which pairing is right."""
    fbref_to_whoscored = {}
    for p in pairs:
        fbref_to_whoscored.setdefault(p["fbref_name"], set()).add(p["whoscored_name"])

    contradictions = {name: names for name, names in fbref_to_whoscored.items() if len(names) > 1}
    if contradictions:
        print(f"WARNING: {len(contradictions)} fbref_name(s) matched to multiple "
              f"different whoscored_names -- SKIPPING these, not resolving them:")
        for name, names in contradictions.items():
            print(f"  {name!r} -> {sorted(names)}")
    return set(contradictions.keys())


def upsert_pair(cur, pair):
    """Reuses an existing player_id if the FBref side is already
    crosswalked; otherwise creates a new players row. Returns the
    player_id used."""
    cur.execute(
        "SELECT player_id FROM player_source_crosswalk "
        "WHERE source = 'fbref' AND source_name = %s",
        (pair["fbref_name"],),
    )
    existing = cur.fetchone()

    if existing:
        player_id = existing[0]
    else:
        cur.execute(
            "INSERT INTO players (canonical_name) VALUES (%s) RETURNING player_id",
            (pair["fbref_name"],),
        )
        player_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO player_source_crosswalk "
            "(player_id, source, source_name, confidence, match_method, verified, notes) "
            "VALUES (%s, 'fbref', %s, %s, %s, %s, %s) "
            "ON CONFLICT (player_id, source, source_name) DO NOTHING",
            (player_id, pair["fbref_name"], pair["confidence"],
             pair["match_method"], pair["verified"], pair["notes"]),
        )

    cur.execute(
        "INSERT INTO player_source_crosswalk "
        "(player_id, source, source_name, confidence, match_method, verified, notes) "
        "VALUES (%s, 'whoscored', %s, %s, %s, %s, %s) "
        "ON CONFLICT (player_id, source, source_name) DO NOTHING",
        (player_id, pair["whoscored_name"], pair["confidence"],
         pair["match_method"], pair["verified"], pair["notes"]),
    )

    return player_id


def main():
    exact_pairs = load_exact_matches()
    reviewed_pairs = load_reviewed_matches()
    print(f"{len(exact_pairs)} exact-normalized pairs, "
          f"{len(reviewed_pairs)} manually-reviewed 'match' pairs.")

    all_pairs = exact_pairs + reviewed_pairs
    skip_names = check_for_contradictions(all_pairs)
    all_pairs = [p for p in all_pairs if p["fbref_name"] not in skip_names]

    conn = get_connection()
    inserted_players = 0
    with conn.cursor() as cur:
        for pair in all_pairs:
            cur.execute(
                "SELECT player_id FROM player_source_crosswalk "
                "WHERE source = 'fbref' AND source_name = %s",
                (pair["fbref_name"],),
            )
            was_new = cur.fetchone() is None
            upsert_pair(cur, pair)
            if was_new:
                inserted_players += 1
        conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM players")
        total_players = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM player_source_crosswalk")
        total_crosswalk = cur.fetchone()[0]

    conn.close()

    print(f"\n{inserted_players} new player identities created this run.")
    print(f"players table now has {total_players} total rows.")
    print(f"player_source_crosswalk table now has {total_crosswalk} total rows.")


if __name__ == "__main__":
    main()
