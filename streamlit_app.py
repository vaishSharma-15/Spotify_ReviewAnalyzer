"""Sonic Intelligence — Streamlit app (frontend + backend in one).

Streamlit runs Python, so it imports the Phase 5 RAG logic (app.rag) directly —
no separate API server needed. Deployable to Streamlit Community Cloud.

Run locally:
  streamlit run streamlit_app.py

On Streamlit Cloud, set GROQ_API_KEY in the app's Secrets.
"""

from __future__ import annotations

import os

import streamlit as st

# Streamlit Cloud provides secrets via st.secrets; mirror into env for groq/rag.
# Locally there may be no secrets file (we use .env instead) — guard for that.
try:
    for _k in ("GROQ_API_KEY", "GROQ_MODEL"):
        if _k in st.secrets:
            os.environ[_k] = st.secrets[_k]
except Exception:  # noqa: BLE001 - no secrets.toml locally is fine
    pass

from app import rag  # noqa: E402  (after env is set)

st.set_page_config(page_title="Spotify Review Discovery Engine", page_icon="🟢", layout="centered")

# ---- Light CSS polish on top of the dark theme (config.toml) ----
st.markdown(
    """
    <style>
      .block-container { padding-top: 3.5rem; max-width: 820px; }
      .si-title { font-size: 26px; font-weight: 800; letter-spacing: -0.01em;
                  margin: 0; line-height: 1.35; display: inline-block;
                  padding: 2px 0; white-space: normal; }
      .si-header { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
      .si-header svg { flex: 0 0 auto; }
      .si-sub { color: #B3B3B3; font-size: 12px; letter-spacing: .06em;
                text-transform: uppercase; margin-bottom: 4px; }
      .si-badge { display:inline-block; background:rgba(29,185,84,.15); color:#53e076;
                  border-radius:9999px; padding:2px 10px; font-size:12px; font-weight:700; }
      .stChatMessage { border-radius: 14px; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner=False)
def _warm():
    """Load the embedding model + Chroma collection once per session."""
    try:
        n = rag._collection().count()
        return {"ok": True, "n": n}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


status = _warm()

# ---- Header ----
SPOTIFY_LOGO = (
    "<svg viewBox='0 0 168 168' width='40' height='40' aria-label='Spotify'>"
    "<path fill='#1DB954' d='M83.996.277C37.747.277.394 37.63.394 83.881c0 "
    "46.251 37.353 83.604 83.602 83.604 46.254 0 83.605-37.353 "
    "83.605-83.604 0-46.249-37.351-83.6-83.605-83.6zm38.404 120.78a5.217 "
    "5.217 0 01-7.18 1.73c-19.662-12.01-44.414-14.73-73.564-8.07a5.222 5.222 "
    "0 01-6.249-3.93 5.213 5.213 0 013.926-6.25c31.9-7.291 59.263-4.15 "
    "81.337 9.34 2.46 1.51 3.24 4.72 1.73 7.18zm10.25-22.805c-1.89 "
    "3.075-5.91 4.045-8.98 2.155-22.51-13.839-56.823-17.846-83.448-9.764-3.453 "
    "1.043-7.1-.903-8.148-4.35a6.538 6.538 0 014.354-8.143c30.413-9.228 "
    "68.222-4.758 94.072 11.127 3.07 1.89 4.04 5.91 2.15 8.98zm.88-23.744c-26.99-16.031-71.52-17.505-97.289-9.684-4.138 "
    "1.255-8.514-1.081-9.768-5.219a7.835 7.835 0 015.221-9.771c29.581-8.98 "
    "78.756-7.245 109.83 11.202a7.823 7.823 0 012.74 10.733c-2.2 3.722-7.02 "
    "4.949-10.73 2.739z'/></svg>"
)
st.markdown(
    f"<div class='si-header'>{SPOTIFY_LOGO}"
    "<span class='si-title'>Spotify Review Discovery Engine</span></div>",
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def _pipeline_stats():
    """Real counts from reviews.db + the vector index, for the backend panel."""
    import sqlite3
    from ingestion.db import DEFAULT_DB_PATH
    out = {"sources": [], "raw": 0, "structured": 0, "indexed": 0}
    try:
        c = sqlite3.connect(DEFAULT_DB_PATH)
        out["raw"] = c.execute("SELECT COUNT(*) FROM raw_reviews").fetchone()[0]
        out["structured"] = c.execute("SELECT COUNT(*) FROM structured_reviews").fetchone()[0]
        out["sources"] = c.execute(
            "SELECT source, COUNT(*) FROM raw_reviews GROUP BY source ORDER BY 2 DESC"
        ).fetchall()
        c.close()
    except Exception:  # noqa: BLE001
        pass
    try:
        out["indexed"] = rag._collection().count()
    except Exception:  # noqa: BLE001
        pass
    return out


# ---- Sidebar: the real backend pipeline, with live counts ----
with st.sidebar:
    st.subheader("⚙️ Backend pipeline")
    st.caption("The system runs offline, then answers from a pre-built index.")
    ps = _pipeline_stats()
    st.markdown(
        f"""
- **① Ingestion** — scraped **{ps['raw']:,}** reviews from 5 sources
- **② Structuring** — **{ps['structured']:,}** passed through the Groq LLM
- **③ Aggregation** — theme / sentiment / segment stats computed
- **④ Indexing** — **{ps['indexed']:,}** vectors in the Chroma store
- **⑤ Query bot** — retrieves + synthesizes per question (below)
"""
    )
    if ps["sources"]:
        st.caption("Reviews by source:")
        for src, n in ps["sources"]:
            st.markdown(f"&nbsp;&nbsp;`{src}` — **{n:,}**", unsafe_allow_html=True)

    st.divider()
    st.subheader("📡 Live activity")
    st.caption("Watch the backend work in real time as it answers your question.")
    # Placeholder the query handler streams stages into, live.
    live_box = st.empty()
    _last = st.session_state.get("last_trace")
    if _last:
        live_box.success("**Last question ran these stages:**\n\n"
                         + "\n".join(f"- {s}" for s in _last))
    else:
        live_box.info("Ask a question to see the pipeline run…")


if status["ok"]:
    st.markdown(f"<span class='si-badge'>{status['n']} reviews indexed</span>",
                unsafe_allow_html=True)
else:
    st.error(f"Index unavailable: {status.get('error')}. "
             "Build it with `python -m indexing.build_index`.")

st.write("")

# ---- Suggested questions (the six key questions) ----
SUGGESTIONS = [
    "Why do users struggle to discover new music?",
    "What are the most common frustrations with recommendations?",
    "What listening behaviors are users trying to achieve?",
    "What causes users to repeatedly listen to the same content?",
    "Which user segments experience different discovery challenges?",
    "What unmet needs emerge consistently across reviews?",
]

if "messages" not in st.session_state:
    st.session_state.messages = []

pending = None
if not st.session_state.messages:
    st.caption("Try one of the key questions:")
    cols = st.columns(2)
    for i, s in enumerate(SUGGESTIONS):
        if cols[i % 2].button(s, key=f"sug{i}", use_container_width=True):
            pending = s

# ---- Render chat history ----
for m in st.session_state.messages:
    with st.chat_message(m["role"], avatar="🎧" if m["role"] == "assistant" else "🧑"):
        st.markdown(m["content"])

# ---- Input ----
typed = st.chat_input("Ask about Spotify music discovery…")
question = pending or typed

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user", avatar="🧑"):
        st.markdown(question)
    with st.chat_message("assistant", avatar="🎧"):
        # Stream each backend stage into the sidebar's live-activity box.
        steps: list[str] = []

        def _on_step(text: str):
            steps.append(text)
            live_box.markdown(
                "**Pipeline running…**\n\n"
                + "\n".join(f"- {s}" for s in steps)
            )

        with st.spinner("Analyzing reviews…"):
            result = rag.answer(question, on_step=_on_step)
        live_box.success("**Done.** Here's what just ran:\n\n"
                         + "\n".join(f"- {s}" for s in steps))
        st.markdown(result["answer"])
    st.session_state.last_trace = steps
    st.session_state.messages.append({
        "role": "assistant", "content": result["answer"],
    })
    st.rerun()
