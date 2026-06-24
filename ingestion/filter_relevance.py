"""Relevance filter — flag reviews related to our discovery themes.

This is a fast, transparent keyword pre-filter (NOT the Phase 2 LLM classifier).
It marks each raw_review with:
  - relevant       1 if it matches any discovery-theme keyword set, else 0
  - matched_theme  the discovery theme id it best matches (or NULL)

It is non-destructive: it only adds/updates columns, so nothing is deleted and
the pass can be re-run safely. Theme ids align with .claude/docs/ThemeTaxonomy.md.

Usage:
  python -m ingestion.filter_relevance            # flag in place + report
  python -m ingestion.filter_relevance --delete   # ALSO delete irrelevant rows
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

from .db import DEFAULT_DB_PATH

# Discovery-relevant themes → keyword patterns. A review is "relevant" if its
# body matches any pattern below. Ordered roughly by specificity; first match
# wins for matched_theme. Patterns are matched case-insensitively on word-ish
# boundaries to limit false positives.
THEME_KEYWORDS: dict[str, list[str]] = {
    "recommendation_repetition": [
        r"same songs?", r"same (artists?|tracks?|playlist)", r"repeat(s|ing|itive|edly)?",
        r"over and over", r"loop(s|ing|ed)?", r"keeps? playing the same",
        r"always the same", r"on repeat",
    ],
    "filter_bubble": [
        r"echo chamber", r"filter bubble", r"already (listen|know|heard)",
        r"stuck (in|with)", r"only (shows|plays|recommends) (what|stuff|songs)",
        r"narrow", r"same genre", r"never anything new",
    ],
    "recommendation_relevance": [
        r"recommend(s|ation|ations|ing|ed)?", r"\bsuggest(s|ion|ions|ed|ing)?\b",
        r"\brecs?\b", r"made for you", r"daily mix", r"discover weekly",
        r"release radar", r"\bradio\b", r"autoplay", r"smart shuffle",
        r"the algorithm", r"\balgorithm(ic)?\b",
    ],
    "discovery_friction": [
        r"discover(y|ing)?", r"find(ing)? new (music|songs|artists)",
        r"new music", r"new artists?", r"explore", r"fresh (music|songs|tracks)",
    ],
    "new_release_artist_discovery": [
        r"new release", r"new album", r"emerging artists?", r"indie",
        r"underground", r"deep cuts?", r"lesser known",
    ],
    "personalization_control": [
        r"not interested", r"\bdislike\b", r"thumbs? down", r"can'?t (remove|exclude|block)",
        r"\bhide (song|artist|track)", r"reset (taste|recommendations)",
        r"\btune (my|the)\b", r"\btaste profile\b", r"too personalized",
    ],
    "findability_search": [
        r"\bsearch(ing)?\b", r"can'?t find", r"hard to find", r"\bbrowse\b",
        r"\bnavigat(e|ion)\b", r"buried", r"\bmenu(s)?\b hard",
    ],
    "catalog_availability": [
        r"not available", r"missing (song|album|artist|track)", r"can'?t find (the )?song",
        r"taken down", r"removed from", r"\bnot on spotify\b", r"region",
    ],
    "onboarding_taste_profile": [
        r"new (account|user)", r"just (downloaded|installed|signed up)",
        r"first (time|week)", r"never asked (my|about) (taste|music)", r"cold start",
    ],
    "social_sharing_discovery": [
        r"friend(s)? activity", r"shared playlist", r"\bblend\b", r"\bjam\b",
        r"see what (my )?friends", r"social",
    ],
    "listening_context": [
        r"\bfocus\b", r"\bworkout\b", r"\bgym\b", r"\bstudy(ing)?\b", r"\bsleep\b",
        r"\bcommute\b", r"\bparty\b", r"\bmood\b", r"\brunning\b", r"\bdriving\b",
    ],
    "library_playlist_mgmt": [
        r"playlist(s)?", r"my library", r"\bsaved? (songs|music)\b", r"\bliked songs\b",
        r"\bqueue\b", r"\bsort(ing)?\b", r"organi[sz]e",
    ],
}

# Pre-compile, preserving theme order for "first match wins".
_COMPILED: list[tuple[str, list[re.Pattern]]] = [
    (theme, [re.compile(p, re.IGNORECASE) for p in pats])
    for theme, pats in THEME_KEYWORDS.items()
]


def classify(body: str) -> str | None:
    """Return the first discovery theme whose keywords match, else None."""
    if not body:
        return None
    for theme, patterns in _COMPILED:
        if any(p.search(body) for p in patterns):
            return theme
    return None


def ensure_columns(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(raw_reviews)")}
    if "relevant" not in cols:
        conn.execute("ALTER TABLE raw_reviews ADD COLUMN relevant INTEGER")
    if "matched_theme" not in cols:
        conn.execute("ALTER TABLE raw_reviews ADD COLUMN matched_theme TEXT")


def run(db_path: Path, delete: bool) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_columns(conn)

    rows = conn.execute("SELECT id, body FROM raw_reviews").fetchall()
    relevant = 0
    for r in rows:
        theme = classify(r["body"] or "")
        conn.execute(
            "UPDATE raw_reviews SET relevant=?, matched_theme=? WHERE id=?",
            (1 if theme else 0, theme, r["id"]),
        )
        if theme:
            relevant += 1
    conn.commit()

    total = len(rows)
    print(f"Scanned {total} reviews — {relevant} relevant, {total - relevant} not.")
    print("\nRelevant by matched theme:")
    for row in conn.execute(
        "SELECT matched_theme, COUNT(*) n FROM raw_reviews "
        "WHERE relevant=1 GROUP BY matched_theme ORDER BY n DESC"
    ):
        print(f"  {row['matched_theme']:32s} {row['n']}")
    print("\nRelevant by source:")
    for row in conn.execute(
        "SELECT source, COUNT(*) n FROM raw_reviews WHERE relevant=1 GROUP BY source"
    ):
        print(f"  {row['source']:16s} {row['n']}")

    if delete:
        cur = conn.execute("DELETE FROM raw_reviews WHERE relevant=0")
        conn.commit()
        conn.execute("VACUUM")
        print(f"\nDeleted {cur.rowcount} irrelevant rows. "
              f"DB now holds {conn.execute('SELECT COUNT(*) FROM raw_reviews').fetchone()[0]}.")
    conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Flag/keep reviews related to discovery themes")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    ap.add_argument("--delete", action="store_true",
                    help="physically delete irrelevant rows (irreversible)")
    args = ap.parse_args(argv)
    run(args.db, args.delete)
    return 0


if __name__ == "__main__":
    sys.exit(main())
