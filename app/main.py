"""Phase 5 FastAPI app — serves the RAG query bot + aggregates + the chat UI.

Run:
  uvicorn app.main:app --reload --port 8000
Then open http://localhost:8000
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import rag

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Sonic Intelligence — Spotify Review Discovery")


class QueryIn(BaseModel):
    question: str
    top_k: int = rag.ANALYZE_K
    theme: Optional[str] = None
    sentiment: Optional[str] = None


@app.get("/health")
def health() -> dict:
    try:
        n = rag._collection().count()
        ok = True
    except Exception:  # noqa: BLE001
        n, ok = 0, False
    return {"status": "ok" if ok else "degraded", "indexed_reviews": n}


@app.post("/api/query")
def query(q: QueryIn) -> dict:
    return rag.answer(q.question, top_k=q.top_k, theme=q.theme, sentiment=q.sentiment)


@app.get("/api/aggregates")
def get_aggregates() -> dict:
    return rag.aggregates()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# Static assets (after routes so "/" resolves to index.html).
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
