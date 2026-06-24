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

st.set_page_config(page_title="Sonic Intelligence", page_icon="🎧", layout="centered")

# ---- Light CSS polish on top of the dark theme (config.toml) ----
st.markdown(
    """
    <style>
      .block-container { padding-top: 2rem; max-width: 820px; }
      .si-title { font-size: 28px; font-weight: 800; letter-spacing: -0.02em; margin: 0; }
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
c1, c2 = st.columns([0.12, 0.88])
with c1:
    st.markdown("<div style='font-size:40px'>🎧</div>", unsafe_allow_html=True)
with c2:
    st.markdown("<div class='si-sub'>Spotify Review Discovery</div>"
                "<div class='si-title'>Sonic Intelligence</div>", unsafe_allow_html=True)

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
        with st.spinner("Analyzing reviews…"):
            result = rag.answer(question)
        st.markdown(result["answer"])
    st.session_state.messages.append({"role": "assistant", "content": result["answer"]})
    st.rerun()
