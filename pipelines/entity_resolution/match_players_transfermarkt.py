"""
Entity resolution, Transfermarkt second pass: scores candidate pairs
from the players_transfermarkt_candidate_pairs VIEW (canonical player
identities, already merged from FBref<->WhoScored, matched against
Transfermarkt's player_name).

Same scoring approach as match_fbref_whoscored.py: Jaro-Winkler +
token-sort on NORMALIZED (lowercased, diacritic-stripped) names, taking
the LOWER of the two as working confidence. Same match_hint triage
categories, for the same reasons -- see that script's docstring for
the full reasoning (verified against real data: string similarity
alone cannot separate genuine matches from genuine same-name-fragment
collisions between different real people).

KEY DIFFERENCE FROM THE FBREF<->WHOSCORED MATCH: blocking here uses
player_team_season_history (reconstructed from player_source_crosswalk
joined back to the FBref/WhoScored stats tables) matched against
eredivisie_transfers' own (own_club_name, season_id) -- NOT the same
direct (team, season_id) columns the first match's tables already
shared. This was added (2026-09-08) after an unblocked first version
produced an unworkable 3,213-row review band -- see
players_transfermarkt_candidate_pairs.sql's comment for the full fix.

MERGE KEY DIFFERS from the FBref<->WhoScored review queue too: this
uses (canonical_player_id, transfermarkt_player_id) -- real, stable
IDs -- rather than name strings, since both sides of this match
already have one. More reliable than a name-based key (immune to any
future renaming/normalization changes to either side).

NO BIRTH-YEAR SIGNAL is included here either -- players.canonical_name
is FBref-derived text with no birth year attached in this table
itself (would need joining back through player_source_crosswalk to
eredivisie_soccerdata_player_season_stats.born -- not done here, a
possible future refinement, not attempted in this first pass).

Output:
  - cleaning_logs/entity_resolution/players_transfermarkt_candidates.csv
    -- every scored candidate pair.
  - cleaning_logs/entity_resolution/players_transfermarkt_review_queue.csv
    -- the 0.5-0.8 band, isolated for manual review. MERGE-SAFE, same
    as the FBref<->WhoScored review queue -- rerunning this script
    preserves any existing decision/notes values.

Nothing is written to player_source_crosswalk by this script --
purely an exploration/review step. Building the actual
Transfermarkt-side crosswalk loader (source='transfermarkt') is a
separate, later step, once a review pass has happened here the same
way it did for the FBref<->WhoScored band.
"""

import csv
import unicodedata
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras
from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler

OUTPUT_DIR = Path("cleaning_logs/entity_resolution")
CANDIDATES_FILE = OUTPUT_DIR / "players_transfermarkt_candidates.csv"
REVIEW_QUEUE_FILE = OUTPUT_DIR / "players_transfermarkt_review_queue.csv"
HIGH_CONFIDENCE_FILE = OUTPUT_DIR / "players_transfermarkt_high_confidence_review.csv"

# Same working boundary as the FBref<->WhoScored match, applied here
# as a starting point -- NOT yet re-validated against this match's own
# real output. Revisit once real candidate pairs have actually been
# looked at, same discipline as before -- don't assume the same
# numbers transfer cleanly to a match with weaker blocking.
REVIEW_BAND_LOW = 0.5
REVIEW_BAND_HIGH = 0.8


def get_connection():
    return psycopg2.connect(dbname="postgres", host="localhost")


def load_candidate_pairs(conn):
    """Reads directly from the players_transfermarkt_candidate_pairs
    VIEW -- no .sql file to read/execute separately, unlike the
    FBref<->WhoScored script, since this query already lives in the
    database as a view."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM players_transfermarkt_candidate_pairs")
        return cur.fetchall()


def normalize_name(name):
    """Lowercases and strips diacritics (Unicode NFKD decomposition,
    dropping combining marks). Identical to match_fbref_whoscored.py's
    version -- kept as a separate copy here rather than a shared import
    since these are two independent scripts in the same folder; worth
    factoring into a shared helper module if a third source-pair match
    is ever built."""
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.lower().split())


def score_pair(name_a, name_b):
    """Returns (jaro_winkler_score, token_sort_score, working_confidence),
    all computed on NORMALIZED names. working_confidence is the LOWER
    of the two."""
    norm_a = normalize_name(name_a)
    norm_b = normalize_name(name_b)

    jw_score = JaroWinkler.normalized_similarity(norm_a, norm_b)
    ts_score = fuzz.token_sort_ratio(norm_a, norm_b) / 100.0
    working_confidence = min(jw_score, ts_score)
    return jw_score, ts_score, working_confidence


def classify_pair(name_a, name_b):
    """Same triage categories as match_fbref_whoscored.py's
    classify_pair() -- see that script's docstring for the reasoning
    and real examples behind each category."""
    norm_a = normalize_name(name_a)
    norm_b = normalize_name(name_b)
    tokens_a = norm_a.split()
    tokens_b = norm_b.split()

    if norm_a == norm_b:
        return "exact_after_normalize"

    if norm_a in norm_b or norm_b in norm_a:
        return "substring_match"

    if (tokens_a and tokens_b and len(tokens_a) >= 2 and len(tokens_b) >= 2
            and tokens_a[0] == tokens_b[0] and tokens_a[-1] == tokens_b[-1]):
        return "given_and_surname_match_extra_middle_token"

    if tokens_a and tokens_b and tokens_a[-1] == tokens_b[-1]:
        return "same_surname_diff_given_name"

    if tokens_a and tokens_b and tokens_a[0] == tokens_b[0]:
        return "same_given_name_diff_surname"

    if tokens_a and tokens_b and set(tokens_a) == set(tokens_b):
        return "same_tokens_reordered"

    return "other"


def score_all_pairs(rows):
    scored_rows = []
    for row in rows:
        jw_score, ts_score, working_confidence = score_pair(
            row["canonical_name"], row["transfermarkt_name"]
        )
        match_hint = classify_pair(row["canonical_name"], row["transfermarkt_name"])
        scored_rows.append({
            "canonical_player_id": row["canonical_player_id"],
            "canonical_name": row["canonical_name"],
            "transfermarkt_player_id": row["transfermarkt_player_id"],
            "transfermarkt_name": row["transfermarkt_name"],
            "trgm_similarity": round(row["trgm_similarity"], 4),
            "jaro_winkler": round(jw_score, 4),
            "token_sort": round(ts_score, 4),
            "working_confidence": round(working_confidence, 4),
            "match_hint": match_hint,
        })
    scored_rows.sort(key=lambda r: r["working_confidence"], reverse=True)
    return scored_rows


def print_diagnostics(df):
    print("\n--- Score distribution ---")
    print(df["working_confidence"].describe())

    exact = (df["working_confidence"] == 1.0).sum()
    high_not_exact = ((df["working_confidence"] >= 0.8) & (df["working_confidence"] < 1.0)).sum()
    review_band = ((df["working_confidence"] >= REVIEW_BAND_LOW) &
                   (df["working_confidence"] < REVIEW_BAND_HIGH)).sum()
    low = (df["working_confidence"] < REVIEW_BAND_LOW).sum()

    print(f"\n--- Band breakdown (of {len(df)} total candidate pairs) ---")
    print(f"Exact match after normalization (== 1.0): {exact}")
    print(f"High confidence, not exact (0.8-1.0):      {high_not_exact}")
    print(f"Review band ({REVIEW_BAND_LOW}-{REVIEW_BAND_HIGH}):"
          f"                    {review_band}")
    print(f"Low confidence (< {REVIEW_BAND_LOW}):"
          f"                        {low}")

    print("\n--- Review band, broken down by triage hint ---")
    review_df = df[(df["working_confidence"] >= REVIEW_BAND_LOW) &
                   (df["working_confidence"] < REVIEW_BAND_HIGH)]
    print(review_df["match_hint"].value_counts())

    dupes = df.groupby("canonical_player_id").size()
    print(f"\n--- Duplicate candidates ---")
    print(f"{(dupes > 1).sum()} canonical players have 2+ Transfermarkt "
          f"candidates -- expected at this stage, same as the "
          f"FBref<->WhoScored match (scoring/review is meant to sort "
          f"these out, not the blocking step).")

    print("\nNo auto-link threshold is applied by this script. The "
          f"review band ({REVIEW_BAND_LOW}-{REVIEW_BAND_HIGH}) is "
          "written to a separate file for manual adjudication.")


def write_review_queue(review_df, target_file=REVIEW_QUEUE_FILE):
    """Merge-safe write, same approach as match_fbref_whoscored.py's
    write_review_queue() -- but keyed on (canonical_player_id,
    transfermarkt_player_id), real stable IDs, rather than name
    strings. Handles both the 0.5-0.8 ambiguous band and the 0.8-1.0
    high-confidence band (see write_high_confidence_queue()) via
    target_file."""
    review_df = review_df.copy()
    if "decision" not in review_df.columns:
        review_df["decision"] = ""
    if "notes" not in review_df.columns:
        review_df["notes"] = ""

    merge_keys = ["canonical_player_id", "transfermarkt_player_id"]

    if target_file.exists():
        existing = pd.read_csv(target_file)
        if "decision" not in existing.columns:
            existing["decision"] = ""
        if "notes" not in existing.columns:
            existing["notes"] = ""

        existing_decisions = existing.set_index(merge_keys)[["decision", "notes"]]

        review_df = review_df.set_index(merge_keys)
        review_df.update(existing_decisions)
        review_df = review_df.reset_index()

        carried_over = existing_decisions[
            (existing_decisions["decision"] != "") & (existing_decisions["decision"].notna())
        ]
        print(f"Preserved {len(carried_over)} existing manual decision(s) "
              f"from the previous {target_file.name}.")

    review_df.to_csv(target_file, index=False)
    return review_df


def write_high_confidence_queue(df):
    """The 0.8-1.0 "high confidence, not exact" band -- deliberately
    EXCLUDED from build_players_transfermarkt_crosswalk.py (not yet
    individually spot-checked). Reuses write_review_queue()'s
    merge-safe logic."""
    high_conf_df = df[(df["working_confidence"] >= 0.8) & (df["working_confidence"] < 1.0)]
    return write_review_queue(high_conf_df, target_file=HIGH_CONFIDENCE_FILE)


def main():
    conn = get_connection()
    rows = load_candidate_pairs(conn)
    conn.close()

    print(f"Loaded {len(rows)} candidate pairs from players_transfermarkt_candidate_pairs.")

    scored_rows = score_all_pairs(rows)
    df = pd.DataFrame(scored_rows)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(CANDIDATES_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=scored_rows[0].keys())
        writer.writeheader()
        writer.writerows(scored_rows)
    print(f"\nWrote {len(scored_rows)} scored candidate pairs to {CANDIDATES_FILE}")

    review_df = df[(df["working_confidence"] >= REVIEW_BAND_LOW) &
                   (df["working_confidence"] < REVIEW_BAND_HIGH)]
    review_df = write_review_queue(review_df)
    print(f"Wrote {len(review_df)} pairs needing manual review to {REVIEW_QUEUE_FILE}")

    high_conf_df = write_high_confidence_queue(df)
    print(f"Wrote {len(high_conf_df)} high-confidence (0.8-1.0) pairs needing "
          f"a lighter spot-check to {HIGH_CONFIDENCE_FILE}")

    print_diagnostics(df)


if __name__ == "__main__":
    main()
