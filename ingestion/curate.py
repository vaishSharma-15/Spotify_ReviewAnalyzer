"""Curate reviews.db for analysis: theme-tag, de-emoji, drop positives.

Steps (all run in one pass, with a one-time backup beforehand):
  1. Classify every row against the discovery themes (filter_relevance) and set
     relevant / matched_theme.
  2. Strip emojis (and other pictographs) from the body text.
  3. Heuristically flag sentiment; delete clear POSITIVE reviews.
  4. Delete rows that are not discovery-relevant or whose body became empty.

Sentiment is a heuristic ONLY — Phase 2's LLM is the accurate pass. We delete
clear positives and keep negative/neutral/mixed (the frustration signal).

Usage: python -m ingestion.curate
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

from .db import DEFAULT_DB_PATH
from .filter_relevance import classify, ensure_columns

# --- emoji / pictograph stripping ------------------------------------------
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # symbols, pictographs, emoji, supplemental
    "\U00002600-\U000027BF"  # misc symbols + dingbats
    "\U0001F1E6-\U0001F1FF"  # regional indicators (flags)
    "\U00002190-\U000021FF"  # arrows
    "\U00002B00-\U00002BFF"  # misc symbols & arrows
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero-width joiner
    "]+",
    flags=re.UNICODE,
)
_WS_RE = re.compile(r"\s+")


def strip_emoji(text: str) -> str:
    if not text:
        return ""
    return _WS_RE.sub(" ", _EMOJI_RE.sub(" ", text)).strip()


# --- sentiment heuristic ---------------------------------------------------
_NEG = re.compile(
    r"\b(bad|terrible|hate|worst|awful|annoying|annoyed|frustrat\w*|broke\w*|"
    r"can'?t|won'?t|doesn'?t|don'?t|didn'?t|stop\w*|fix|problem|issue|bug\w*|"
    r"crash\w*|ads?|ridiculous|useless|disappoint\w*|repetit\w*|stuck|glitch\w*|"
    r"error|charge\w*|expensive|cancel\w*|refund|sucks?|garbage|worse|unable|"
    r"fail\w*|missing|lost|no longer|never|why|hard|difficult|wish|should|"
    r"not work\w*|laggy?|slow|freeze\w*|forced?)\b",
    re.IGNORECASE,
)
_POS = re.compile(
    r"\b(love|loved|loving|great|awesome|amazing|perfect|best|excellent|"
    r"wonderful|fantastic|good|nice|favou?rite|enjoy\w*|happy|brilliant|"
    r"flawless|superb|incredible|10/10|5 stars?|thank you|thanks)\b",
    re.IGNORECASE,
)


def is_positive(body: str, rating) -> bool:
    has_neg = bool(_NEG.search(body or ""))
    has_pos = bool(_POS.search(body or ""))
    if rating is not None:
        if rating >= 4 and not has_neg:
            return True
        return False  # 1-3 stars, or 4-5 with complaints -> keep
    # no rating (reddit / social / forum): praise with no complaint = positive
    return has_pos and not has_neg


def run(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_columns(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(raw_reviews)")}
    if "sentiment" not in cols:
        conn.execute("ALTER TABLE raw_reviews ADD COLUMN sentiment TEXT")

    rows = conn.execute("SELECT id, body, rating FROM raw_reviews").fetchall()
    start = len(rows)
    deleted_pos = deleted_irrel = deleted_empty = emoji_cleaned = 0

    for r in rows:
        new_body = strip_emoji(r["body"] or "")
        if new_body != (r["body"] or ""):
            emoji_cleaned += 1

        theme = classify(new_body)
        positive = is_positive(new_body, r["rating"])
        sentiment = "positive" if positive else "neg_or_neutral"

        # deletion rules
        if not new_body:
            conn.execute("DELETE FROM raw_reviews WHERE id=?", (r["id"],))
            deleted_empty += 1
            continue
        if positive:
            conn.execute("DELETE FROM raw_reviews WHERE id=?", (r["id"],))
            deleted_pos += 1
            continue
        if theme is None:
            conn.execute("DELETE FROM raw_reviews WHERE id=?", (r["id"],))
            deleted_irrel += 1
            continue
        conn.execute(
            "UPDATE raw_reviews SET body=?, relevant=1, matched_theme=?, sentiment=? WHERE id=?",
            (new_body, theme, sentiment, r["id"]),
        )

    conn.commit()
    conn.execute("VACUUM")
    kept = conn.execute("SELECT COUNT(*) FROM raw_reviews").fetchone()[0]

    print(f"Started with {start} reviews.")
    print(f"  emoji-cleaned bodies : {emoji_cleaned}")
    print(f"  deleted (positive)   : {deleted_pos}")
    print(f"  deleted (off-theme)  : {deleted_irrel}")
    print(f"  deleted (empty)      : {deleted_empty}")
    print(f"  KEPT                 : {kept}")
    print("\nKept by theme:")
    for row in conn.execute(
        "SELECT matched_theme, COUNT(*) n FROM raw_reviews GROUP BY matched_theme ORDER BY n DESC"
    ):
        print(f"  {row['matched_theme']:32s} {row['n']}")
    conn.close()


if __name__ == "__main__":
    run(DEFAULT_DB_PATH)
    sys.exit(0)
