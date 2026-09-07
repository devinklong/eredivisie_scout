"""
Entity resolution, phase 1: FBref <-> WhoScored candidate-pair matching.

Runs fbref_whoscored_candidate_pairs.sql (a loose pg_trgm-based first
pass, blocked on team + season_id) to get a manageable candidate set,
then layers real scoring on top in Python:

  - Jaro-Winkler similarity (rewards shared name prefixes -- good for
    typos/spelling variants)
  - token-sort ratio (handles word-order differences, e.g.
    "de Jong, Frenkie" vs "Frenkie de Jong")
  - the LOWER of the two scores is used as the working confidence, not
    the higher -- using the max would let two genuinely different names
    score high just because one check happened to like them

Both scores are computed on a NORMALIZED version of each name
(lowercased, diacritics stripped via Unicode NFKD decomposition), not
the raw string. This was found to matter in practice: an early version
of this script scored genuine same-person matches like "Vaclav Cerny"
vs "Vaclav Cerny" (raw: "Václav Černý" vs "Václav Cerny") at only 0.50,
and pure case differences ("Jeroen Van der Lely" vs "Jeroen van der
Lely") at 0.7895 instead of 1.0 -- both were dragging real matches into
the same confidence band as genuinely different players, which made
that band impossible to reason about. Fixing normalization moved the
0.5-0.8 band from 198 pairs down to 182 (out of 4,266 total
candidates) -- a real but modest improvement, confirming normalization
was not the dominant source of ambiguity in that band.

KNOWN NORMALIZATION GAP: Turkish dotless i (u+0131, 'ı') is its own
distinct Unicode character, not a letter-plus-combining-mark, so NFKD
decomposition does not convert it to plain 'i'. Confirmed via a real
example: "Abdurrahman Burak Sayın" vs "Burak Sayin" still scores <1.0
after normalization for this reason. Not special-cased here -- revisit
if more Turkish names surface as a real pattern rather than a single
instance.

WHAT NORMALIZATION DOES NOT AND CANNOT FIX: confirmed via a full
real-batch review (2026-09-05) of the post-normalization 0.5-0.8 band
that genuine matches (nicknames, mononyms, truncated middle/surnames --
e.g. "Izzy Brown"/"Isaiah Brown", "Memphis"/"Memphis Depay",
"Maximilian Woeber"/"Max Woeber") and genuine DIFFERENT real people who
happen to share a name fragment (e.g. "Christian Eriksen"/"Christian
Poulsen", "Frenkie de Jong"/"Siem de Jong"/"Luuk de Jong", "Quinten
Timber"/"Jurrien Timber" -- actual brothers, "Youri Baas"/"Youri
Regeer") land in the SAME confidence range. No single threshold can
separate these two groups using string similarity alone -- doing so
requires either external knowledge (a nickname dictionary) or an
independent signal this data doesn't yet have (birth year -- WhoScored
has none; see below). This is why no auto-link threshold is applied
anywhere in this script.

classify_pair() adds a rough triage HINT (not a verdict) to help a
human reviewer scan the ambiguous band faster, by flagging which known
ambiguous pattern a given pair matches (substring/truncation, a
same-surname or same-given-name collision, or a same-tokens-reordered
case) -- see its docstring, and the "other" category's real examples
below for why "same tokens, different order" needed adding as its own
flagged pattern rather than being left unclassified.

NO BIRTH-YEAR SIGNAL is included anywhere in this script --
eredivisie_whoscored_player_season_stats has no birth-year column at
all (only the FBref/soccerdata side has 'born'). This becomes usable
once Transfermarkt bio data is loaded, not before.

Output:
  - cleaning_logs/entity_resolution/fbref_whoscored_candidates.csv --
    every scored candidate pair, for full review. Fully overwritten on
    every run -- nothing manual is ever recorded here.
  - cleaning_logs/entity_resolution/fbref_whoscored_review_queue.csv --
    just the 0.5-0.8 "genuinely ambiguous" band, isolated for focused
    manual review, with 'decision' and 'notes' columns for that review
    to be recorded in directly. MERGE-SAFE: rerunning this script
    preserves any existing decision/notes values (matched on
    fbref_name + whoscored_name + team + season_id) rather than
    overwriting them -- see write_review_queue()'s docstring. A pair
    whose key no longer appears in a new run (e.g. it fell out of the
    review band after an upstream data change) has its old decision
    dropped, since there's no surviving row to attach it to.

Nothing is written to Postgres by this script -- this is purely an
exploration/review step, not a crosswalk-table loader. That's the next
phase, once a real reviewed judgment exists for enough of this band to
trust an approach for the rest.
"""

import csv
import unicodedata
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras
from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler

SQL_FILE = Path(__file__).parent / "fbref_whoscored_candidate_pairs.sql"
OUTPUT_DIR = Path("cleaning_logs/entity_resolution")
CANDIDATES_FILE = OUTPUT_DIR / "fbref_whoscored_candidates.csv"
REVIEW_QUEUE_FILE = OUTPUT_DIR / "fbref_whoscored_review_queue.csv"

# The "genuinely ambiguous, needs a human" band -- confirmed via a real
# batch review (2026-09-05) that this range mixes true matches and true
# non-matches inseparably by string similarity alone. Pairs scoring
# 1.0 are treated as safe auto-links; pairs scoring below this range
# are treated as safe non-matches (also spot-checked against a real
# batch -- see module docstring). This is a working boundary based on
# one real run, not a permanently fixed constant -- revisit as more of
# the review queue gets adjudicated.
REVIEW_BAND_LOW = 0.5
REVIEW_BAND_HIGH = 0.8


def get_connection():
    return psycopg2.connect(dbname="postgres", host="localhost")


def load_candidate_pairs(conn):
    """Runs the blocked pg_trgm query directly from the .sql file --
    kept in one place so the query and this script never drift apart."""
    query = SQL_FILE.read_text()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query)
        return cur.fetchall()


def normalize_name(name):
    """Lowercases and strips diacritics (Unicode NFKD decomposition,
    dropping combining marks) -- e.g. 'Vaclav Cerny' -> 'vaclav cerny'.
    Whitespace is collapsed but Dutch surname particles (van, de, ten,
    etc.) are deliberately left in place, not stripped -- stripping
    them risks losing real distinguishing signal (e.g. 'de Jong' vs
    'de Ligt'). See module docstring for the known Turkish-character
    gap in this approach."""
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.lower().split())


def score_pair(fbref_name, whoscored_name):
    """Returns (jaro_winkler_score, token_sort_score, working_confidence),
    all computed on NORMALIZED names. working_confidence is the LOWER
    of the two -- see module docstring."""
    norm_fbref = normalize_name(fbref_name)
    norm_whoscored = normalize_name(whoscored_name)

    jw_score = JaroWinkler.normalized_similarity(norm_fbref, norm_whoscored)
    ts_score = fuzz.token_sort_ratio(norm_fbref, norm_whoscored) / 100.0
    working_confidence = min(jw_score, ts_score)
    return jw_score, ts_score, working_confidence


def classify_pair(fbref_name, whoscored_name):
    """Adds a rough triage hint to help a human reviewer scan the
    manual-review band faster -- NOT a matching decision. Confirmed via
    a real batch (2026-09-05) that string-similarity scoring alone
    cannot separate genuine nickname/truncation matches (e.g. 'Izzy
    Brown' / 'Isaiah Brown', a real match) from genuine same-surname or
    same-given-name collisions between different real people (e.g.
    'Frenkie de Jong' / 'Siem de Jong') -- both patterns land in the
    same score range. This hint flags the PATTERN, not the verdict."""
    norm_a = normalize_name(fbref_name)
    norm_b = normalize_name(whoscored_name)
    tokens_a = norm_a.split()
    tokens_b = norm_b.split()

    if norm_a == norm_b:
        return "exact_after_normalize"

    # One full name is a substring of the other -- classic truncation/
    # mononym pattern (e.g. "memphis" in "memphis depay").
    if norm_a in norm_b or norm_b in norm_a:
        return "substring_match"

    # Same surname (last token), different given name -- the
    # "de Jong x3" collision pattern.
    if tokens_a and tokens_b and tokens_a[-1] == tokens_b[-1]:
        return "same_surname_diff_given_name"

    # Same given name (first token), different surname -- the
    # "Youri Baas / Youri Regeer" collision pattern.
    if tokens_a and tokens_b and tokens_a[0] == tokens_b[0]:
        return "same_given_name_diff_surname"

    # Same set of tokens, different order -- e.g. "Abass Issah" /
    # "Issah Abass". Found via a real 'other'-bucket review (2026-09-05):
    # this pattern is NOT a safe auto-match signal either -- "Leroy
    # George" / "George Cox" matches the same shape (shared token
    # "George") but are almost certainly two different real people,
    # "George" coincidentally being a first name for one and a surname
    # for the other. Flagged as its own category so it's tracked, not
    # silently left in "other".
    if tokens_a and tokens_b and set(tokens_a) == set(tokens_b):
        return "same_tokens_reordered"

    return "other"


def score_all_pairs(rows):
    scored_rows = []
    for row in rows:
        jw_score, ts_score, working_confidence = score_pair(
            row["fbref_name"], row["whoscored_name"]
        )
        match_hint = classify_pair(row["fbref_name"], row["whoscored_name"])
        scored_rows.append({
            "fbref_name": row["fbref_name"],
            "whoscored_name": row["whoscored_name"],
            "team": row["team"],
            "season_id": row["season_id"],
            "trgm_similarity": round(row["trgm_similarity"], 4),
            "jaro_winkler": round(jw_score, 4),
            "token_sort": round(ts_score, 4),
            "working_confidence": round(working_confidence, 4),
            "match_hint": match_hint,
        })
    scored_rows.sort(key=lambda r: r["working_confidence"], reverse=True)
    return scored_rows


def print_diagnostics(df):
    """Reproduces, as code, the exploratory checks used to arrive at
    REVIEW_BAND_LOW/HIGH and the conclusions in this module's docstring
    -- run every time so the reasoning is visible to anyone who forks
    this repo, not just recoverable from chat history. None of this
    changes scoring or output; it's purely diagnostic printing."""
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

    dupes = df.groupby(["fbref_name", "team", "season_id"]).size()
    print(f"\n--- Duplicate candidates ---")
    print(f"{(dupes > 1).sum()} FBref (name, team, season) combos have "
          f"2+ WhoScored candidates -- expected at this stage (scoring "
          f"is meant to sort these out, not the blocking step).")

    print("\nNo auto-link threshold is applied by this script. The "
          f"review band ({REVIEW_BAND_LOW}-{REVIEW_BAND_HIGH}) is "
          "written to a separate file for manual adjudication -- see "
          "module docstring for why this band can't be resolved by "
          "scoring alone.")


def write_review_queue(review_df):
    """Writes the review queue, preserving any manual 'decision'/'notes'
    values already recorded on disk for pairs that still exist in the
    current run. Without this, rerunning match_fbref_whoscored.py (e.g.
    after a schema/data change upstream) would silently blow away any
    hand-adjudication work already done on
    fbref_whoscored_review_queue.csv -- confirmed as a real risk before
    manual review of that file had actually started (2026-09-06), fixed
    here before it could cause real damage.

    Merge key: (fbref_name, whoscored_name, team, season_id) -- the
    same natural key identifying a candidate pair throughout this
    script. If a pair's key no longer appears in the new run (e.g. the
    underlying data changed enough that it fell out of the review
    band), its old decision is simply dropped, since it's not decidable
    which surviving pair it would have applied to."""
    review_df = review_df.copy()
    if "decision" not in review_df.columns:
        review_df["decision"] = ""
    if "notes" not in review_df.columns:
        review_df["notes"] = ""

    merge_keys = ["fbref_name", "whoscored_name", "team", "season_id"]

    if REVIEW_QUEUE_FILE.exists():
        existing = pd.read_csv(REVIEW_QUEUE_FILE)
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
              f"from the previous {REVIEW_QUEUE_FILE.name}.")

    review_df.to_csv(REVIEW_QUEUE_FILE, index=False)
    return review_df


def main():
    conn = get_connection()
    rows = load_candidate_pairs(conn)
    conn.close()

    print(f"Loaded {len(rows)} candidate pairs from the pg_trgm first pass.")

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

    print_diagnostics(df)


if __name__ == "__main__":
    main()
