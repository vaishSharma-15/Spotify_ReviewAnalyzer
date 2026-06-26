"""Phase 2.5 — deep re-classification of the `user_segment` field only.

Why: the first structuring pass assigned segments as one of seven fields with a
flat list, which over-tagged power_user / music_explorer (it inferred identity
from the complaint topic). This pass re-labels user_segment with a focused,
per-axis prompt + strict evidence rule (see UserSegmentTaxonomy.md), leaving
theme/sentiment/etc. untouched.

Resumable: each refined row is stamped with SEGMENT_VERSION, so re-running picks
up where it stopped (handy when Groq's daily token cap is hit).

Usage:
  python -m structuring.segment_refine --all
  python -m structuring.segment_refine --limit 200
  python -m structuring.segment_refine --status
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ingestion.db import DEFAULT_DB_PATH
from structuring import schema as S
from structuring.schema import DISCOVERY_THEMES

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

SEGMENT_VERSION = "seg-2"

# Axis membership — used to enforce "at most one segment per axis".
AXES = [
    ["power_user", "casual_listener", "new_user", "returning_user"],   # engagement
    ["free_tier", "premium", "family_plan", "student_plan"],           # plan
    ["music_explorer", "genre_specialist", "mood_context_listener",
     "podcast_audiobook_user", "artist_creator"],                      # identity
]

# Compact prompt — kept short to maximize throughput under Groq's 6000 TPM cap.
SEG_SYSTEM = (
    "Label the reviewer's user_segment (WHO they are, NOT their complaint). "
    "Output JSON {\"user_segment\":[ids]}. Assign an id ONLY if a phrase proves "
    "it; else []. Don't infer identity from the complaint (a 'bad discovery' "
    "review is NOT music_explorer). At most one per axis.\n"
    "engagement: power_user(heavy/long-term/curates), casual_listener(light/"
    "passive), new_user(just joined), returning_user(came back/switched).\n"
    "plan: free_tier(ads/can't skip), premium(pays), family_plan, student_plan.\n"
    "identity: music_explorer(loves NEW music), genre_specialist(specific genre), "
    "mood_context_listener(gym/study/sleep/commute), podcast_audiobook_user, "
    "artist_creator. No signal -> []."
)

_RETRY_RE = re.compile(r"try again in ([\d.]+)s")


def ensure_column(conn: sqlite3.Connection) -> None:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(structured_reviews)")]
    if "segment_version" not in cols:
        conn.execute("ALTER TABLE structured_reviews ADD COLUMN segment_version TEXT")
        conn.commit()


def pending(conn, limit):
    q = """
        SELECT s.review_id, r.title, r.body
        FROM structured_reviews s JOIN raw_reviews r ON r.id = s.review_id
        WHERE s.status='ok'
          AND s.theme IN ({themes})
          AND (s.segment_version IS NULL OR s.segment_version != ?)
        ORDER BY s.review_id
    """.format(themes=",".join("?" * len(DISCOVERY_THEMES)))
    params = list(DISCOVERY_THEMES) + [SEGMENT_VERSION]
    rows = conn.execute(q, params).fetchall()
    return rows[:limit] if limit else rows


def normalize(segs) -> list[str]:
    """Validate ids, enforce one-per-axis, fall back to unspecified."""
    if isinstance(segs, str):
        segs = [segs]
    if not isinstance(segs, list):
        segs = []
    valid = [s for s in segs if s in S.USER_SEGMENTS and s != "unspecified"]
    out = []
    for axis in AXES:
        picked = next((s for s in valid if s in axis), None)
        if picked:
            out.append(picked)
    # keep any valid non-axis ids (none currently, but future-proof)
    return out or ["unspecified"]


def refine_one(client, model, title, body):
    text = (f"Title: {title}\n" if title else "") + f"Review: {body or ''}"
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model, temperature=0, max_tokens=80,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": SEG_SYSTEM},
                          {"role": "user", "content": text}],
            )
            data = json.loads(resp.choices[0].message.content or "{}")
            return normalize(data.get("user_segment"))
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if "429" in msg and ("per day" in msg or "TPD" in msg):
                raise SystemExit("Daily token cap reached — re-run later to resume.")
            if "429" in msg:
                m = _RETRY_RE.search(msg)
                time.sleep(min(float(m.group(1)) + 1, 30) if m else 15)
                continue
            if attempt == 2:
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Phase 2.5 — refine user_segment")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    ensure_column(conn)

    if args.status:
        done = conn.execute("SELECT COUNT(*) FROM structured_reviews "
                            "WHERE segment_version=?", (SEGMENT_VERSION,)).fetchone()[0]
        todo = len(pending(conn, None))
        print(f"segment_version {SEGMENT_VERSION}: refined={done}, pending={todo}")
        return 0

    import groq
    if not os.environ.get("GROQ_API_KEY"):
        print("No GROQ_API_KEY set."); return 1
    client = groq.Groq()
    model = os.environ.get("GROQ_MODEL", S.MODEL)

    rows = pending(conn, None if args.all else (args.limit or 200))
    if not rows:
        print("Nothing to refine — all up to date."); return 0
    print(f"Refining user_segment for {len(rows)} reviews ({SEGMENT_VERSION})…")

    def work(row):
        segs = refine_one(client, model, row["title"], row["body"])
        return row["review_id"], segs

    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for rid, segs in ex.map(work, rows):
            if segs is None:
                continue
            conn.execute(
                "UPDATE structured_reviews SET user_segment=?, segment_version=? "
                "WHERE review_id=?",
                (json.dumps(segs), SEGMENT_VERSION, rid))
            done += 1
            if done % 50 == 0:
                conn.commit(); print(f"  …{done}/{len(rows)}")
    conn.commit()
    print(f"Done. Refined {done} reviews.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
