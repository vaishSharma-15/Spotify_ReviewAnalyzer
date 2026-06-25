"""Phase 4 runner — build the Chroma vector index from structured reviews.

Reads status='ok' rows from structured_reviews joined with raw_reviews (for the
citation text + source + link), embeds each review body with the local model
(indexing.embed), and upserts into a persistent Chroma collection. Metadata
(theme, sentiment, user_segment, source, source_url, severity) is stored
alongside each vector so Phase 5 can filter and cite directly from a hit.

The index is a sidecar to reviews.db (which stays the single source of truth);
it never triggers scraping. Idempotent — re-running upserts by review_id.

Usage:
  python -m indexing.build_index            # build/update the index
  python -m indexing.build_index --rebuild  # drop and rebuild from scratch
  python -m indexing.build_index --status   # show index size
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from ingestion.db import DEFAULT_DB_PATH
from structuring.schema import DISCOVERY_THEMES
from .embed import EMBED_MODEL, embed_texts

# Chroma persists here, next to reviews.db. Sidecar store, not the SoT.
INDEX_DIR = Path(__file__).resolve().parent.parent / "chroma_index"
COLLECTION = "spotify_reviews"


def get_collection(rebuild: bool = False):
    import chromadb

    client = chromadb.PersistentClient(path=str(INDEX_DIR))
    if rebuild:
        try:
            client.delete_collection(COLLECTION)
        except Exception:  # noqa: BLE001 - fine if it doesn't exist yet
            pass
    # cosine space; we also pass normalized embeddings, so this is consistent.
    return client.get_or_create_collection(
        name=COLLECTION,
        metadata={"embedding_model": EMBED_MODEL, "hnsw:space": "cosine"},
    )


def fetch_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    # Index only discovery-relevant themes so the chatbot never retrieves
    # off-topic reviews (app bugs, pricing, ads, etc.).
    placeholders = ",".join("?" * len(DISCOVERY_THEMES))
    return conn.execute(
        f"""
        SELECT r.id, r.body, r.title, r.source, r.source_url,
               s.theme, s.sentiment, s.user_segment, s.severity_score,
               s.frustration
        FROM structured_reviews s
        JOIN raw_reviews r ON r.id = s.review_id
        WHERE s.status = 'ok'
          AND s.theme IN ({placeholders})
          AND r.body IS NOT NULL AND length(trim(r.body)) > 0
        ORDER BY r.id
        """,
        DISCOVERY_THEMES,
    ).fetchall()


def build(db_path: Path, rebuild: bool, batch: int = 256) -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = fetch_rows(conn)
    if not rows:
        print("No structured reviews to index yet (run Phase 2 first).")
        return 0

    collection = get_collection(rebuild=rebuild)

    total = 0
    for start in range(0, len(rows), batch):
        chunk = rows[start:start + batch]
        ids = [str(r["id"]) for r in chunk]
        # Embed the review text (title + body) for semantic match to questions.
        docs = [((r["title"] + ". ") if r["title"] else "") + r["body"] for r in chunk]
        embeddings = embed_texts(docs)
        metadatas = []
        for r in chunk:
            try:
                segs = json.loads(r["user_segment"]) or ["unspecified"]
            except (TypeError, json.JSONDecodeError):
                segs = ["unspecified"]
            metadatas.append({
                "theme": r["theme"] or "other",
                "sentiment": r["sentiment"] or "neutral",
                "user_segment": ",".join(segs),  # Chroma metadata must be scalar
                "severity_score": int(r["severity_score"] or 1),
                "source": r["source"] or "",
                "source_url": r["source_url"] or "",
                "frustration": (r["frustration"] or "")[:300],
            })
        collection.upsert(
            ids=ids,
            embeddings=[e.tolist() for e in embeddings],
            documents=docs,
            metadatas=metadatas,
        )
        total += len(chunk)
        print(f"  indexed {total}/{len(rows)}")

    print(f"\nDone. Chroma collection '{COLLECTION}' now holds {collection.count()} vectors.")
    print(f"  model: {EMBED_MODEL}")
    print(f"  path : {INDEX_DIR}")
    return total


def status() -> None:
    try:
        import chromadb
    except ImportError:
        print("chromadb not installed — run: pip install chromadb")
        return
    if not INDEX_DIR.exists():
        print("No index built yet.")
        return
    client = chromadb.PersistentClient(path=str(INDEX_DIR))
    try:
        col = client.get_collection(COLLECTION)
    except Exception:  # noqa: BLE001
        print("No collection yet.")
        return
    print(f"collection '{COLLECTION}': {col.count()} vectors")
    print(f"  model: {col.metadata.get('embedding_model')}")
    print(f"  path : {INDEX_DIR}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 4 — build the Chroma vector index")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    ap.add_argument("--rebuild", action="store_true", help="drop and rebuild the index")
    ap.add_argument("--status", action="store_true", help="show index size and exit")
    args = ap.parse_args(argv)

    if args.status:
        status()
        return 0

    try:
        import chromadb  # noqa: F401
    except ImportError:
        print("chromadb not installed — run: pip install chromadb sentence-transformers")
        return 1

    build(args.db, rebuild=args.rebuild)
    return 0


if __name__ == "__main__":
    sys.exit(main())
