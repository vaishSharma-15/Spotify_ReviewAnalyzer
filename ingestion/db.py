"""reviews.db — the single source of truth.

Phase 1 only owns the ``raw_reviews`` table; later phases add their own tables
to the same database. Writes are idempotent: a row whose content_hash already
exists is skipped (edge case I1), so re-running ingestion never duplicates data.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

from .base import RawReview

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "reviews.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_reviews (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT    NOT NULL,
    source_url    TEXT,
    author        TEXT,
    title         TEXT,
    body          TEXT    NOT NULL,
    raw_body      TEXT,
    rating        INTEGER,
    lang          TEXT,
    created_at    TEXT,
    ingested_at   TEXT    NOT NULL,
    content_hash  TEXT    NOT NULL UNIQUE,
    body_empty    INTEGER NOT NULL DEFAULT 0,  -- edge case I2/I6
    uncitable     INTEGER NOT NULL DEFAULT 0   -- edge case I9 (no usable link)
);
CREATE INDEX IF NOT EXISTS idx_raw_reviews_source     ON raw_reviews(source);
CREATE INDEX IF NOT EXISTS idx_raw_reviews_created_at ON raw_reviews(created_at);
"""


class ReviewStore:
    """Thin wrapper over the SQLite datastore for Phase 1 writes."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def upsert_many(self, reviews: Iterable[RawReview]) -> tuple[int, int]:
        """Insert reviews, skipping duplicates. Returns (inserted, skipped)."""
        inserted = skipped = 0
        with self._connect() as conn:
            for r in reviews:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO raw_reviews
                        (source, source_url, author, title, body, raw_body,
                         rating, lang, created_at, ingested_at, content_hash,
                         body_empty, uncitable)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        r.source, r.source_url, r.author, r.title, r.body,
                        r.raw_body, r.rating, r.lang, r.created_at,
                        r.ingested_at, r.content_hash,
                        1 if r.is_empty else 0,
                        1 if not r.source_url else 0,
                    ),
                )
                if cur.rowcount:
                    inserted += 1
                else:
                    skipped += 1
        return inserted, skipped

    def count(self, source: str | None = None) -> int:
        with self._connect() as conn:
            if source:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM raw_reviews WHERE source = ?",
                    (source,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS n FROM raw_reviews").fetchone()
            return row["n"]

    def counts_by_source(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT source, COUNT(*) AS n FROM raw_reviews GROUP BY source"
            ).fetchall()
            return {row["source"]: row["n"] for row in rows}
