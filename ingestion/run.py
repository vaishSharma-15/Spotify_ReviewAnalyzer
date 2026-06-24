"""Phase 1 CLI orchestrator.

Runs one or more source collectors and writes normalized rows into reviews.db.
This is the offline, on-demand entry point — it never participates in the
real-time query path.

Examples:
  python -m ingestion.run --all --limit 200
  python -m ingestion.run --source app_store --source reddit --limit 100
  python -m ingestion.run --status
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .collectors import COLLECTORS
from .db import DEFAULT_DB_PATH, ReviewStore

# Load .env if python-dotenv is available (optional convenience).
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def run_source(name: str, store: ReviewStore, limit: int) -> tuple[int, int]:
    collector = COLLECTORS[name]()
    ok, reason = collector.available()
    if not ok:
        print(f"[{name}] skipped — {reason}")
        return 0, 0
    print(f"[{name}] collecting up to {limit} reviews…")
    try:
        inserted, skipped = store.upsert_many(collector.collect(limit))
    except Exception as exc:  # noqa: BLE001 - one source must not kill the run
        print(f"[{name}] ERROR: {exc}")
        return 0, 0
    print(f"[{name}] inserted={inserted} skipped(dupes)={skipped}")
    return inserted, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 1 — ingest Spotify reviews")
    parser.add_argument(
        "--source", action="append", choices=sorted(COLLECTORS), default=[],
        help="source to collect (repeatable). Omit with --all for everything.",
    )
    parser.add_argument("--all", action="store_true", help="collect from all sources")
    parser.add_argument("--limit", type=int, default=200, help="max reviews per source")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="path to reviews.db")
    parser.add_argument("--status", action="store_true", help="show DB counts and exit")
    args = parser.parse_args(argv)

    store = ReviewStore(args.db)

    if args.status:
        counts = store.counts_by_source()
        total = store.count()
        print(f"reviews.db: {args.db}")
        for src in sorted(COLLECTORS):
            print(f"  {src:16s} {counts.get(src, 0)}")
        print(f"  {'TOTAL':16s} {total}")
        return 0

    sources = sorted(COLLECTORS) if args.all else args.source
    if not sources:
        parser.error("specify --all or at least one --source (or use --status)")

    total_inserted = 0
    for name in sources:
        inserted, _ = run_source(name, store, args.limit)
        total_inserted += inserted

    print(f"\nDone. {total_inserted} new reviews. DB now holds {store.count()} total.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
