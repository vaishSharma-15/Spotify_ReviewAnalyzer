"""RAG core — retrieve cited reviews + aggregates, then synthesize via Groq.

Read-only and instant: queries hit the pre-built Chroma index and the
materialized aggregate tables. Never scrapes. Every answer is grounded in the
retrieved reviews and must cite them (source + link).
"""

from __future__ import annotations

import json
import os
import sqlite3
from functools import lru_cache
from pathlib import Path

from ingestion.db import DEFAULT_DB_PATH
from indexing.build_index import COLLECTION, INDEX_DIR
from indexing.embed import embed_texts
from structuring import schema as S

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

TOP_K = 8
# Below this top-hit similarity, the question is off-topic for this tool.
RELEVANCE_THRESHOLD = 0.35
OUT_OF_SCOPE_MSG = (
    "I am Spotify Reviewer Analyser 🎧. Ask me regarding meaningful music "
    "discovery and reducing repetitive listening behavior only. Thank you 🙏"
)
# Groq free tier caps a single request at ~6000 tokens/min, so we feed a
# bounded, truncated sample. The answer still reflects ALL reviews via the
# Phase 3 aggregate percentages; the sample provides representative citations.
ANALYZE_K = 12     # reviews fed to the model per request
SNIPPET_CHARS = 240  # max chars per review in the prompt
CITE_K = 4         # key supporting reviews surfaced as citations


@lru_cache(maxsize=1)
def _collection():
    import chromadb

    return chromadb.PersistentClient(path=str(INDEX_DIR)).get_collection(COLLECTION)


def retrieve(question: str, top_k: int = TOP_K, theme: str | None = None,
             sentiment: str | None = None) -> list[dict]:
    """Semantic search over the review index, with optional metadata filters."""
    emb = embed_texts([question])[0].tolist()
    where = {}
    if theme:
        where["theme"] = theme
    if sentiment:
        where["sentiment"] = sentiment
    res = _collection().query(
        query_embeddings=[emb],
        n_results=top_k,
        where=where or None,
    )
    hits = []
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]
    ids = res.get("ids", [[]])[0]
    for rid, doc, meta, dist in zip(ids, docs, metas, dists):
        hits.append({
            "review_id": int(rid),
            "text": doc,
            "theme": meta.get("theme"),
            "sentiment": meta.get("sentiment"),
            "user_segment": meta.get("user_segment"),
            "severity_score": meta.get("severity_score"),
            "source": meta.get("source"),
            "source_url": meta.get("source_url"),
            "similarity": round(1 - dist, 3),
        })
    return hits


def aggregates(db_path: Path = DEFAULT_DB_PATH) -> dict:
    """Phase 3 aggregate tables, for grounding answers in numbers."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    def rows(q):
        try:
            return [dict(r) for r in conn.execute(q).fetchall()]
        except sqlite3.OperationalError:
            return []

    data = {
        "meta": {r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM agg_meta")}
        if _has(conn, "agg_meta") else {},
        "theme_distribution": rows(
            "SELECT theme,n,pct,avg_severity,neg_pct,low_n FROM agg_theme_distribution ORDER BY n DESC"),
        "top_frustrations": rows(
            "SELECT rank,theme,frustration,n,avg_severity,score,low_n FROM agg_top_frustrations ORDER BY rank LIMIT 15"),
        "segment_distribution": rows(
            "SELECT user_segment,n,pct_of_reviews,low_n FROM agg_segment_distribution ORDER BY n DESC"),
        "sentiment_by_theme": rows(
            "SELECT theme,sentiment,n,pct_within_theme FROM agg_sentiment_by_theme"),
    }
    conn.close()
    return data


def _has(conn, table) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _aggregate_brief(agg: dict) -> str:
    """Compact text summary of aggregates to ground the LLM in numbers."""
    lines = []
    td = agg.get("theme_distribution", [])[:6]
    if td:
        lines.append("Top complaint topics: " + "; ".join(
            f"{_readable_theme(t['theme'])} (~{round(t['pct'])}%)" for t in td))
    return "\n".join(lines)


SYSTEM = (
    "You are a friendly chatbot that explains what Spotify users complain about. "
    "Answer in simple, everyday language a normal person can understand instantly "
    "— like texting a smart friend, not writing a report. The reviews given are "
    "complaints; focus on the problems. Rules:\n"
    "- Use plain words. Avoid jargon and avoid snake_case terms (say 'finding new "
    "music', not 'discovery_friction').\n"
    "- Keep it to 2-3 short sentences. Start with the main reason in plain English, "
    "then briefly explain why.\n"
    "- Mention at most ONE simple, rounded number (e.g. 'about 85%' or 'most "
    "complaints'), only if it helps. Don't stack multiple percentages.\n"
    "- No headings, no bullet points, no [1]/[2] citation markers, no quoting "
    "reviews. Just talk naturally.\n"
    "- If you don't have enough info, say so simply. Never make things up."
)


def _readable_theme(theme: str) -> str:
    """Turn a snake_case theme id into plain words."""
    return (theme or "other").replace("_", " ")


def _theme_brief_for(agg: dict, themes: list[str]) -> str:
    """Plain-language stats lines for the themes most relevant to this question."""
    td = {t["theme"]: t for t in agg.get("theme_distribution", [])}
    out = []
    for th in themes:
        r = td.get(th)
        if r:
            out.append(f"- {_readable_theme(th)}: {r['n']} complaints, "
                       f"about {round(r['neg_pct'])}% negative")
    return "\n".join(out)


def answer(question: str, top_k: int = ANALYZE_K, theme: str | None = None,
           sentiment: str | None = None, model: str | None = None,
           on_step=None) -> dict:
    """Full RAG turn: retrieve broadly → analyze by theme → one cited answer.

    Focuses on NEGATIVE reviews by default (this is a frustration-discovery
    tool); positive reviews are excluded unless a sentiment is explicitly set.

    ``on_step(text)`` — optional callback fired as each backend stage completes,
    so a UI can show the pipeline working in real time.
    """
    import time as _t
    sentiment = sentiment or "negative"
    trace = []

    def step(text: str):
        trace.append(text)
        if on_step:
            try:
                on_step(text)
            except Exception:  # noqa: BLE001 - UI callback must never break the answer
                pass

    _t0 = _t.time()
    step("🔎 Reading your question…")
    emb_dim = len(embed_texts([question])[0])
    step(f"🧬 Turned it into a {emb_dim}-dim meaning vector "
         f"({(_t.time()-_t0)*1000:.0f} ms)")
    _t1 = _t.time()
    hits = retrieve(question, top_k=top_k, theme=theme, sentiment=sentiment)
    step(f"📚 Searched all {_collection().count()} indexed reviews → "
         f"reading the {len(hits)} most relevant {sentiment} ones "
         f"({(_t.time()-_t1)*1000:.0f} ms)")
    agg = aggregates()
    step(f"📊 Loaded stats over {agg.get('meta', {}).get('n_reviews', '1,659')} "
         f"analyzed reviews")

    # Out-of-scope guard: if nothing is semantically close, the question isn't
    # about Spotify music discovery — return the fixed scope message.
    top_sim = max((h["similarity"] for h in hits), default=0.0)
    if not hits or top_sim < RELEVANCE_THRESHOLD:
        step(f"⛔ Closest match only {top_sim:.0%} similar → off-topic, skipping the LLM")
        return {"answer": OUT_OF_SCOPE_MSG, "citations": [],
                "themes_analyzed": [], "evidence_count": 0,
                "out_of_scope": True, "aggregates": agg, "trace": trace}

    # Which themes dominate the retrieved evidence — that's what we analyze.
    from collections import Counter
    theme_counts = Counter(h["theme"] for h in hits if h["theme"])
    top_themes = [t for t, _ in theme_counts.most_common(4)]
    step("🏷️ Main themes in these reviews: "
         + ", ".join(_readable_theme(t) for t in top_themes))

    # Breakdown of the analyzed reviews, with counts + % — shown under the answer.
    n_hits = len(hits)
    theme_breakdown = [
        {"theme": _readable_theme(t), "n": c, "pct": round(c / n_hits * 100)}
        for t, c in theme_counts.most_common()
    ]
    source_counts = Counter((h.get("source") or "unknown") for h in hits)
    source_breakdown = [
        {"source": s, "n": c, "pct": round(c / n_hits * 100)}
        for s, c in source_counts.most_common()
    ]

    # Feed the model the broad evidence set so it analyzes the theme as a whole.
    evidence = "\n".join(
        f"[{i+1}] (theme={h['theme']}, sentiment={h['sentiment']}) "
        f"{h['text'][:SNIPPET_CHARS]}"
        for i, h in enumerate(hits)
    )
    prompt = (
        f"Question: {question}\n\n"
        f"Most relevant complaint topics: "
        f"{', '.join(_readable_theme(t) for t in top_themes)}\n\n"
        f"Topic stats (from {agg.get('meta', {}).get('n_reviews', '1,659')} reviews):\n"
        f"{_theme_brief_for(agg, top_themes)}\n\n"
        f"Overall context:\n{_aggregate_brief(agg)}\n\n"
        f"Real complaints to learn from (context only — don't quote them):\n{evidence}\n\n"
        "Now answer the question in 2-3 short, simple sentences a normal person "
        "can understand right away. Plain words only, at most one rounded number, "
        "no jargon, no lists, no citations."
    )

    _used_model = model or os.environ.get("GROQ_MODEL", S.MODEL)
    step(f"🤖 Asking the Groq LLM to summarize {len(hits)} reviews into one answer…")
    _t2 = _t.time()
    try:
        import re
        import groq
        if not os.environ.get("GROQ_API_KEY"):
            raise RuntimeError("GROQ_API_KEY not set")
        client = groq.Groq()

        def _call():
            resp = client.chat.completions.create(
                model=_used_model,
                temperature=0.3,
                max_tokens=300,
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt},
                ],
            )
            return resp.choices[0].message.content or ""

        # Groq free tier caps at 6000 tokens/min; on a 429, wait the suggested
        # time and retry (up to twice) instead of failing the whole answer.
        text = ""
        for attempt in range(3):
            try:
                text = _call()
                break
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                if "rate_limit" not in msg and "429" not in msg:
                    raise
                if attempt == 2:
                    raise
                m = re.search(r"try again in ([\d.]+)s", msg)
                wait = min(float(m.group(1)) + 0.5, 15) if m else 6.0
                step(f"⏳ Hit the per-minute rate limit — waiting {wait:.0f}s and retrying…")
                _t.sleep(wait)
        step(f"✅ Answer ready — built from {len(hits)} reviews "
             f"({(_t.time()-_t2)*1000:.0f} ms)")
    except Exception as exc:  # noqa: BLE001 - surface a clear error, still return citations
        text = f"(Could not generate a synthesized answer: {exc})"
        step(f"⚠️ LLM call failed: {exc}")

    # No review cards — the answer is a self-contained natural synthesis.
    return {
        "answer": text,
        "citations": [],
        "themes_analyzed": top_themes,
        "evidence_count": len(hits),
        "theme_breakdown": theme_breakdown,
        "source_breakdown": source_breakdown,
        "index_total": _collection().count(),
        "aggregates": agg,
        "trace": trace,
    }
