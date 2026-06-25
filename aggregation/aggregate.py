"""Phase 3 runner — build materialized aggregate tables from structured_reviews.

Metrics (per PhaseWiseArchitecture.md):
  - theme distribution (count + %)
  - top frustrations ranked by frequency AND severity
  - sentiment by theme
  - breakdown by user segment (and theme × segment cross-tab for Q5)

Only status='ok' structured rows are aggregated; quarantined rows are excluded
(edge case A3). Tables are rebuilt atomically each run and stamped in agg_meta
with build time + row count, so stale aggregates can't be served (edge case A8).
Low-sample cells are flagged via `low_n` so the bot can caveat % claims (A2).

Usage:
  python -m aggregation.aggregate          # rebuild all aggregates
  python -m aggregation.aggregate --show   # rebuild + print a summary
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from ingestion.db import DEFAULT_DB_PATH
from structuring.schema import DISCOVERY_THEMES

LOW_N = 5  # cells with fewer than this are flagged low_n (edge case A2)

SCHEMA = """
DROP TABLE IF EXISTS agg_theme_distribution;
DROP TABLE IF EXISTS agg_sentiment_by_theme;
DROP TABLE IF EXISTS agg_segment_distribution;
DROP TABLE IF EXISTS agg_theme_by_segment;
DROP TABLE IF EXISTS agg_top_frustrations;
DROP TABLE IF EXISTS agg_meta;

CREATE TABLE agg_theme_distribution (
    theme TEXT PRIMARY KEY, n INTEGER, pct REAL,
    avg_severity REAL, neg_pct REAL, low_n INTEGER
);
CREATE TABLE agg_sentiment_by_theme (
    theme TEXT, sentiment TEXT, n INTEGER, pct_within_theme REAL,
    PRIMARY KEY (theme, sentiment)
);
CREATE TABLE agg_segment_distribution (
    user_segment TEXT PRIMARY KEY, n INTEGER, pct_of_reviews REAL, low_n INTEGER
);
CREATE TABLE agg_theme_by_segment (
    user_segment TEXT, theme TEXT, n INTEGER,
    PRIMARY KEY (user_segment, theme)
);
CREATE TABLE agg_top_frustrations (
    rank INTEGER PRIMARY KEY, theme TEXT, frustration TEXT,
    n INTEGER, avg_severity REAL, score REAL, low_n INTEGER
);
CREATE TABLE agg_meta (
    key TEXT PRIMARY KEY, value TEXT
);
"""


def fetch_ok(conn) -> list[sqlite3.Row]:
    # Only the discovery-relevant themes (the six key questions); catch-all
    # themes like app_performance / pricing are excluded from the deliverable.
    placeholders = ",".join("?" * len(DISCOVERY_THEMES))
    return conn.execute(
        f"""SELECT theme, sentiment, frustration, user_segment, severity_score
            FROM structured_reviews
            WHERE status='ok' AND theme IN ({placeholders})""",
        DISCOVERY_THEMES,
    ).fetchall()


def build(conn: sqlite3.Connection) -> dict:
    conn.executescript(SCHEMA)
    rows = fetch_ok(conn)
    total = len(rows)

    theme_n = Counter()
    theme_sev = defaultdict(list)
    theme_neg = Counter()
    sent_by_theme = Counter()           # (theme, sentiment) -> n
    seg_n = Counter()                   # segment -> n (multi-axis, counted once per review it appears in)
    theme_seg = Counter()               # (segment, theme) -> n
    frus = defaultdict(lambda: [0, []])  # (theme, frustration_norm) -> [count, [severities]]

    for r in rows:
        theme = r["theme"]
        theme_n[theme] += 1
        theme_sev[theme].append(r["severity_score"] or 0)
        if r["sentiment"] == "negative":
            theme_neg[theme] += 1
        sent_by_theme[(theme, r["sentiment"])] += 1

        try:
            segs = json.loads(r["user_segment"]) or ["unspecified"]
        except (TypeError, json.JSONDecodeError):
            segs = ["unspecified"]
        for seg in set(segs):  # count each segment once per review
            seg_n[seg] += 1
            theme_seg[(seg, theme)] += 1

        f = (r["frustration"] or "").strip().lower()
        if f:
            key = (theme, f)
            frus[key][0] += 1
            frus[key][1].append(r["severity_score"] or 0)

    # --- theme distribution ---
    for theme, n in theme_n.items():
        sev = theme_sev[theme]
        conn.execute(
            "INSERT INTO agg_theme_distribution VALUES (?,?,?,?,?,?)",
            (theme, n, round(100 * n / total, 2) if total else 0,
             round(sum(sev) / len(sev), 2) if sev else 0,
             round(100 * theme_neg[theme] / n, 2) if n else 0,
             1 if n < LOW_N else 0),
        )

    # --- sentiment by theme ---
    for (theme, sentiment), n in sent_by_theme.items():
        conn.execute(
            "INSERT INTO agg_sentiment_by_theme VALUES (?,?,?,?)",
            (theme, sentiment, n,
             round(100 * n / theme_n[theme], 2) if theme_n[theme] else 0),
        )

    # --- segment distribution + theme×segment ---
    for seg, n in seg_n.items():
        conn.execute(
            "INSERT INTO agg_segment_distribution VALUES (?,?,?,?)",
            (seg, n, round(100 * n / total, 2) if total else 0, 1 if n < LOW_N else 0),
        )
    for (seg, theme), n in theme_seg.items():
        conn.execute("INSERT INTO agg_theme_by_segment VALUES (?,?,?)", (seg, theme, n))

    # --- top frustrations: ranked by frequency AND severity (score = n * avg_sev) ---
    ranked = []
    for (theme, f), (n, sevs) in frus.items():
        avg = sum(sevs) / len(sevs) if sevs else 0
        ranked.append((theme, f, n, round(avg, 2), round(n * avg, 2)))
    ranked.sort(key=lambda x: x[4], reverse=True)
    for i, (theme, f, n, avg, score) in enumerate(ranked[:50], 1):
        conn.execute(
            "INSERT INTO agg_top_frustrations VALUES (?,?,?,?,?,?,?)",
            (i, theme, f, n, avg, score, 1 if n < LOW_N else 0),
        )

    # --- meta (edge case A8: stamp build so stale aggregates can't be served) ---
    model_version = conn.execute(
        "SELECT model_version FROM structured_reviews WHERE status='ok' LIMIT 1"
    ).fetchone()
    meta = {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_structured_reviews": str(total),
        "model_version": model_version[0] if model_version else "n/a",
        "low_n_threshold": str(LOW_N),
    }
    for k, v in meta.items():
        conn.execute("INSERT INTO agg_meta VALUES (?,?)", (k, v))
    conn.commit()
    return {"total": total, "themes": len(theme_n), "segments": len(seg_n),
            "frustrations": len(ranked)}


def show(conn) -> None:
    meta = dict(conn.execute("SELECT key, value FROM agg_meta").fetchall())
    print(f"Aggregates built {meta.get('built_at')} over "
          f"{meta.get('n_structured_reviews')} structured reviews "
          f"({meta.get('model_version')})\n")

    print("Theme distribution:")
    for r in conn.execute("SELECT theme,n,pct,avg_severity,neg_pct,low_n "
                          "FROM agg_theme_distribution ORDER BY n DESC"):
        flag = "  ⚠low_n" if r[5] else ""
        print(f"  {r[0]:30s} {r[1]:4d}  {r[2]:5.1f}%  sev={r[3]:.1f}  neg={r[4]:.0f}%{flag}")

    print("\nTop 10 frustrations (freq × severity):")
    for r in conn.execute("SELECT rank,theme,frustration,n,avg_severity,score "
                          "FROM agg_top_frustrations ORDER BY rank LIMIT 10"):
        print(f"  {r[0]:2d}. [{r[1]}] {r[2][:55]!r}  n={r[3]} sev={r[4]} score={r[5]}")

    print("\nTop user segments:")
    for r in conn.execute("SELECT user_segment,n,pct_of_reviews,low_n "
                          "FROM agg_segment_distribution ORDER BY n DESC LIMIT 10"):
        flag = "  ⚠low_n" if r[3] else ""
        print(f"  {r[0]:24s} {r[1]:4d}  {r[2]:5.1f}%{flag}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 3 — build aggregates")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    ap.add_argument("--show", action="store_true", help="print a summary after building")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    stats = build(conn)
    print(f"Built aggregates from {stats['total']} structured reviews "
          f"({stats['themes']} themes, {stats['segments']} segments, "
          f"{stats['frustrations']} distinct frustrations).")
    if args.show:
        print()
        show(conn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
