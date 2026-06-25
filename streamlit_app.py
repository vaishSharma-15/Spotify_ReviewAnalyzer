"""Spotify Analyst — terminal-style Streamlit dashboard (frontend + backend).

Streamlit runs Python, so it imports the Phase 5 RAG logic (app.rag) directly —
no separate API server needed. Deployable to Streamlit Community Cloud.

Run locally:
  streamlit run streamlit_app.py

On Streamlit Cloud, set GROQ_API_KEY in the app's Secrets.
"""

from __future__ import annotations

import os
import time
from datetime import datetime

import streamlit as st

# Streamlit Cloud provides secrets via st.secrets; mirror into env for groq/rag.
try:
    for _k in ("GROQ_API_KEY", "GROQ_MODEL"):
        if _k in st.secrets:
            os.environ[_k] = st.secrets[_k]
except Exception:  # noqa: BLE001 - no secrets.toml locally is fine
    pass

from app import rag  # noqa: E402  (after env is set)

st.set_page_config(page_title="Spotify Analyst", page_icon="🟢",
                   layout="wide", initial_sidebar_state="expanded")

# ----------------------------------------------------------------------------
# Theme / CSS — terminal-style high-contrast dark UI (from DESIGN.md)
# ----------------------------------------------------------------------------
st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap');
      :root {
        --bg:#131313; --panel:#1c1b1b; --panel-2:#201f1f; --panel-3:#2a2a2a;
        --primary:#1db954; --primary-bright:#53e076; --on-primary:#003914;
        --text:#e5e2e1; --dim:#869585; --stroke:rgba(255,255,255,.08);
        --error:#ffb4ab;
      }
      html, body, [class*="css"] { font-family:'Plus Jakarta Sans',system-ui,sans-serif; }
      .stApp { background:var(--bg); }
      .block-container { padding-top:1rem; padding-bottom:6rem; max-width:1100px; }
      /* hide default streamlit chrome — but KEEP the header so the sidebar
         expand/collapse arrow stays clickable. Just make it transparent. */
      #MainMenu, footer { visibility:hidden; }
      header[data-testid="stHeader"] { background:transparent; }
      /* keep the sidebar collapse/expand control visible & on top */
      [data-testid="stSidebarCollapsedControl"],
      [data-testid="collapsedControl"] { visibility:visible !important; z-index:1000; }

      /* sidebar */
      section[data-testid="stSidebar"] { background:#0e0e0e; border-right:1px solid var(--stroke); }
      .brand { display:flex; align-items:center; gap:10px; padding:8px 4px 18px; }
      .brand .mark { width:30px;height:30px;border-radius:7px;background:var(--primary);
                     display:grid;place-items:center;color:var(--on-primary);font-weight:800; }
      .brand .name { font-size:19px;font-weight:800;color:var(--text);letter-spacing:-.01em; }
      .brand .name .g { color:var(--primary-bright); }
      .navlabel { font-family:'JetBrains Mono',monospace; }
      .sess { position:relative; margin-top:18px; padding-top:14px; border-top:1px solid var(--stroke);
              color:var(--dim); font-family:'JetBrains Mono',monospace; font-size:12px; }
      .sess b { color:var(--text); display:block; font-size:13px; letter-spacing:.04em; }

      /* top status bar */
      .statusbar { display:flex; align-items:center; gap:22px; flex-wrap:wrap;
                   font-family:'JetBrains Mono',monospace; font-size:12.5px; letter-spacing:.04em;
                   color:var(--dim); border-bottom:1px solid var(--stroke);
                   padding:4px 2px 14px; margin-bottom:10px; }
      .statusbar .live { color:var(--primary-bright); font-weight:700; display:flex; align-items:center; gap:7px; }
      .statusbar .dot { width:8px;height:8px;border-radius:50%;background:var(--primary-bright);
                        box-shadow:0 0 8px var(--primary-bright); animation:blink 1.6s infinite; }
      .statusbar b { color:var(--text); }
      @keyframes blink { 0%,100%{opacity:1} 50%{opacity:.35} }

      .botname { font-family:'JetBrains Mono',monospace; color:var(--primary-bright);
                 font-weight:700; font-size:14px; letter-spacing:.04em; }
      .botname span { color:var(--dim); font-weight:400; margin-left:8px; font-size:12px; }
      .viewhead { font-family:'JetBrains Mono',monospace; color:var(--primary-bright);
                  font-weight:700; letter-spacing:.08em; font-size:13px; margin-bottom:2px; }

      /* chat bubbles */
      .stChatMessage { background:transparent; }
      .stChatMessage [data-testid="stChatMessageContent"] { font-size:14px; }

      /* buttons / chips */
      .stButton>button { border-radius:9999px; border:1px solid var(--stroke);
                         background:var(--panel-3); color:var(--text); font-size:13px;
                         font-weight:600; transition:.15s; }
      .stButton>button:hover { border-color:var(--primary); color:var(--primary-bright); }

      /* metric cards */
      .card { background:var(--panel); border:1px solid var(--stroke); border-radius:12px;
              padding:14px 16px; }
      .card .k { font-family:'JetBrains Mono',monospace; color:var(--dim); font-size:11px;
                 letter-spacing:.08em; text-transform:uppercase; }
      .card .v { color:var(--text); font-size:26px; font-weight:800; }

      .barrow { display:flex; align-items:center; gap:10px; margin:6px 0; font-size:13px; }
      .barrow .lbl { width:210px; color:var(--text); font-size:13px; }
      .barrow .track { flex:1; height:10px; background:var(--panel-3); border-radius:9999px; overflow:hidden; }
      .barrow .fill { height:100%; background:linear-gradient(90deg,var(--primary),var(--primary-bright)); border-radius:9999px; }
      .barrow .num { font-family:'JetBrains Mono',monospace; color:var(--dim); width:64px; text-align:right; }
      .logline { font-family:'JetBrains Mono',monospace; font-size:13px; color:var(--text);
                 padding:3px 0; border-bottom:1px dashed var(--stroke); }
      .logline .t { color:var(--primary-bright); }

      /* evidence summary footer under a bot answer */
      .evidence { margin-top:12px; padding:11px 14px; background:var(--panel);
                  border:1px solid var(--stroke); border-left:3px solid var(--primary);
                  border-radius:10px; }
      .evidence .eh { font-family:'JetBrains Mono',monospace; color:var(--primary-bright);
                      font-size:11px; font-weight:700; letter-spacing:.08em; margin-bottom:6px; }
      .evidence .er { font-size:12.5px; color:var(--dim); line-height:1.7;
                      font-family:'JetBrains Mono',monospace; }
      .evidence .er b { color:var(--text); }
    </style>
    """,
    unsafe_allow_html=True,
)


# ----------------------------------------------------------------------------
# Data helpers
# ----------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def _warm():
    try:
        return {"ok": True, "n": rag._collection().count()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _pipeline_stats():
    # Not cached: these are instant SQLite/Chroma counts and must always reflect
    # the deployed data (a stale cache once showed 1,000 after a 1,659 update).
    import sqlite3
    from ingestion.db import DEFAULT_DB_PATH
    out = {"sources": [], "raw": 0, "structured": 0, "on_theme": 0, "indexed": 0}
    try:
        c = sqlite3.connect(DEFAULT_DB_PATH)
        from structuring.schema import DISCOVERY_THEMES
        out["raw"] = c.execute("SELECT COUNT(*) FROM raw_reviews").fetchone()[0]
        out["structured"] = c.execute("SELECT COUNT(*) FROM structured_reviews").fetchone()[0]
        ph = ",".join("?" * len(DISCOVERY_THEMES))
        out["on_theme"] = c.execute(
            f"SELECT COUNT(*) FROM structured_reviews WHERE status='ok' AND theme IN ({ph})",
            DISCOVERY_THEMES,
        ).fetchone()[0]
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


def _agg():
    try:
        return rag.aggregates()
    except Exception:  # noqa: BLE001
        return {}


status = _warm()
ps = _pipeline_stats()
agg = _agg()

# session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "view" not in st.session_state:
    st.session_state.view = "TERMINAL"
if "last_trace" not in st.session_state:
    st.session_state.last_trace = []
if "history" not in st.session_state:
    st.session_state.history = []

NAV = [("TERMINAL", "🖥️"), ("ANALYTICS", "📈"), ("LOGS", "🕘"),
       ("SENTIMENT", "🙂"), ("QUERY HISTORY", "🔎")]

SUGGESTIONS = [
    "Why do users struggle to discover new music?",
    "What are the most common frustrations with recommendations?",
    "What listening behaviors are users trying to achieve?",
    "What causes users to repeatedly listen to the same content?",
    "Which user segments experience different discovery challenges?",
    "What unmet needs emerge consistently across reviews?",
]


# ----------------------------------------------------------------------------
# Sidebar — brand + nav + session
# ----------------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        "<div class='brand'><div class='mark'>📊</div>"
        "<div class='name'>Spotify<span class='g'> Analyst</span></div></div>",
        unsafe_allow_html=True,
    )
    for name, icon in NAV:
        active = st.session_state.view == name
        if st.button(f"{icon}  {name}", key=f"nav_{name}",
                     use_container_width=True, type="primary" if active else "secondary"):
            st.session_state.view = name
            st.rerun()
    st.markdown(
        "<div class='sess'>👤 <b>USER_SESSION_01</b>ADMINISTRATOR</div>",
        unsafe_allow_html=True,
    )


# ----------------------------------------------------------------------------
# Top status bar
# ----------------------------------------------------------------------------
analyzed = ps.get("structured", 0)
db_state = "STABLE" if status.get("ok") else "ERROR"
st.markdown(
    f"<div class='statusbar'>"
    f"<span class='live'><span class='dot'></span>LIVE: {analyzed:,} ANALYZED</span>"
    f"<span>SYNC: <b>{datetime.now().strftime('%I:%M:%S %p')}</b></span>"
    f"<span>DB_STATUS: <b>{db_state}</b></span>"
    f"<span>INDEX: <b>{ps.get('indexed', 0):,}</b></span>"
    f"</div>",
    unsafe_allow_html=True,
)


def _readable(t: str) -> str:
    return (t or "other").replace("_", " ")


SOURCE_LABELS = {
    "app_store": "App Store reviews",
    "play_store": "Play Store reviews",
    "reddit": "Reddit discussions",
    "community_forum": "Community forums",
    "social": "Social media conversations",
}


def _source_label(s: str) -> str:
    base = (s or "").replace(" (LIVE)", "").strip()
    return SOURCE_LABELS.get(base, _readable(s).title())


def _bar(label, value, total, num=None):
    pct = (value / total * 100) if total else 0
    st.markdown(
        f"<div class='barrow'><div class='lbl'>{label}</div>"
        f"<div class='track'><div class='fill' style='width:{pct:.0f}%'></div></div>"
        f"<div class='num'>{num if num is not None else value}</div></div>",
        unsafe_allow_html=True,
    )


def _answer_footer(meta: dict):
    """Evidence summary under a bot answer: # reviews, themes, sources (w/ %)."""
    if not meta or not meta.get("evidence_count"):
        return
    read_n = meta["evidence_count"]
    base = meta.get("analysis_base", 0)
    total = meta.get("index_total", 0)
    # Lead with the TRUE analysis base (all reviews in the relevant themes),
    # with the full-dataset theme counts; the snippet sample is secondary.
    themes = " · ".join(f"{t['theme']} {t['n']} ({t['pct']}%)"
                        for t in meta.get("theme_full", [])[:5])
    sources = " · ".join(f"{_source_label(s['source'])} {s['n']} ({s['pct']}%)"
                         for s in meta.get("source_breakdown", []))
    html = (
        "<div class='evidence'>"
        f"<div class='eh'>📊 ANALYSIS SUMMARY</div>"
        + (f"<div class='er'><b>Based on {base:,} reviews</b> about this question's "
           f"themes" + (f" &nbsp;(of {total:,} on-theme total)" if total else "") + "</div>"
           if base else "")
        + (f"<div class='er'><b>Themes:</b> {themes}</div>" if themes else "")
        + (f"<div class='er'><b>Sources (sample):</b> {sources}</div>" if sources else "")
        + "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# VIEW: TERMINAL (chat)
# ----------------------------------------------------------------------------
def view_terminal():
    st.markdown(
        f"<div class='botname'>ANALYST_BOT <span>{datetime.now().strftime('%I:%M:%S')}</span></div>",
        unsafe_allow_html=True,
    )
    if not status["ok"]:
        st.error(f"Index unavailable: {status.get('error')}. "
                 "Build it with `python -m indexing.build_index`.")
        return

    if not st.session_state.messages:
        st.caption("> Query the review intelligence base. Try a key question:")
        cols = st.columns(2)
        for i, s in enumerate(SUGGESTIONS):
            if cols[i % 2].button(s, key=f"sug{i}", use_container_width=True):
                st.session_state._pending = s
                st.rerun()

    for m in st.session_state.messages:
        with st.chat_message(m["role"], avatar="🟢" if m["role"] == "assistant" else "🧑"):
            st.markdown(m["content"])
            if m.get("meta"):
                _answer_footer(m["meta"])

    typed = st.chat_input("> ask ANALYST_BOT about Spotify music discovery…")
    question = st.session_state.pop("_pending", None) or typed
    if not question:
        return

    st.session_state.messages.append({"role": "user", "content": question})
    st.session_state.history.append(
        {"q": question, "t": datetime.now().strftime('%I:%M:%S %p')})
    with st.chat_message("user", avatar="🧑"):
        st.markdown(question)

    with st.chat_message("assistant", avatar="🟢"):
        steps: list[str] = []
        live = st.empty()

        def _on_step(text: str):
            steps.append(text)
            live.markdown("```\n" + "\n".join(steps) + "\n```")

        with st.spinner("analyzing reviews…"):
            result = rag.answer(question, on_step=_on_step)
        live.empty()
        st.markdown(result["answer"])
        meta = {k: result.get(k) for k in
                ("evidence_count", "analysis_base", "index_total",
                 "theme_full", "theme_breakdown", "source_breakdown")}
        _answer_footer(meta)

    st.session_state.last_trace = steps
    st.session_state.messages.append(
        {"role": "assistant", "content": result["answer"], "meta": meta})
    st.rerun()


# ----------------------------------------------------------------------------
# VIEW: ANALYTICS
# ----------------------------------------------------------------------------
def view_analytics():
    # --- Pipeline funnel: every count, scraped → used ---
    st.markdown("<div class='viewhead'>// PIPELINE FUNNEL</div>", unsafe_allow_html=True)
    st.caption("From raw scrape to the reviews actually powering the chatbot.")
    cards = [
        ("Scraped (raw)", "~5,952", "pulled from 5 sources"),
        ("Curated", f"{ps['raw']:,}", "negative · no emoji"),
        ("Analyzed by LLM", f"{ps['structured']:,}", "theme / sentiment / severity"),
        ("On-question themes", f"{ps['on_theme']:,}", "the 12 discovery themes"),
        ("Indexed (in use)", f"{ps['indexed']:,}", "searchable vectors"),
    ]
    cols = st.columns(len(cards))
    for col, (k, v, sub) in zip(cols, cards):
        col.markdown(
            f"<div class='card'><div class='k'>{k}</div>"
            f"<div class='v'>{v}</div>"
            f"<div class='k' style='text-transform:none;margin-top:4px'>{sub}</div></div>",
            unsafe_allow_html=True,
        )
    st.caption("Scraped & theme-relevant figures are from the pipeline run history "
               "(the DB now stores the final curated set).")
    st.write("")

    # --- Reviews by source ---
    st.markdown("<div class='viewhead'>// REVIEWS BY SOURCE</div>", unsafe_allow_html=True)
    src_total = sum(n for _, n in ps["sources"]) or 1
    for src, n in ps["sources"]:
        _bar(_source_label(src), n, src_total, num=f"{n:,} · {round(n/src_total*100)}%")
    st.write("")

    # --- Theme distribution ---
    st.markdown("<div class='viewhead'>// THEME DISTRIBUTION</div>", unsafe_allow_html=True)
    st.caption("What users complain about, across all analyzed reviews.")
    td = agg.get("theme_distribution", [])
    total = sum(t["n"] for t in td) or 1
    for t in td[:18]:
        _bar(_readable(t["theme"]), t["n"], total,
             num=f"{t['n']} · {round(t['pct'])}%")
    if not td:
        st.info("No aggregates yet — run `python -m aggregation.aggregate`.")
        return
    st.write("")

    # --- User segments ---
    sd = agg.get("segment_distribution", [])
    if sd:
        st.markdown("<div class='viewhead'>// USER SEGMENTS</div>", unsafe_allow_html=True)
        seg_total = sum(s["n"] for s in sd) or 1
        for s in sd[:14]:
            _bar(_readable(s["user_segment"]), s["n"], seg_total,
                 num=f"{s['n']} · {round(s.get('pct_of_reviews', 0))}%")


# ----------------------------------------------------------------------------
# VIEW: SENTIMENT
# ----------------------------------------------------------------------------
def view_sentiment():
    st.markdown("<div class='viewhead'>// SENTIMENT BY THEME</div>", unsafe_allow_html=True)
    st.caption("Share of negative sentiment within each complaint theme.")
    td = agg.get("theme_distribution", [])
    for t in sorted(td, key=lambda r: r.get("neg_pct", 0), reverse=True)[:14]:
        _bar(_readable(t["theme"]), round(t.get("neg_pct", 0)), 100,
             num=f"{round(t.get('neg_pct', 0))}% neg")
    if not td:
        st.info("No aggregates yet — run `python -m aggregation.aggregate`.")


# ----------------------------------------------------------------------------
# VIEW: LOGS (live backend trace of last query)
# ----------------------------------------------------------------------------
def view_logs():
    st.markdown("<div class='viewhead'>// BACKEND TRACE — LAST QUERY</div>", unsafe_allow_html=True)
    st.caption("The real pipeline stages that ran for your most recent question.")
    if not st.session_state.last_trace:
        st.info("No query run yet. Ask something in TERMINAL to populate the log.")
        return
    for s in st.session_state.last_trace:
        st.markdown(f"<div class='logline'><span class='t'>›</span> {s}</div>",
                    unsafe_allow_html=True)
    st.write("")
    st.markdown("<div class='viewhead'>// REVIEWS BY SOURCE</div>", unsafe_allow_html=True)
    total = sum(n for _, n in ps["sources"]) or 1
    for src, n in ps["sources"]:
        _bar(_source_label(src), n, total, num=f"{n:,}")


# ----------------------------------------------------------------------------
# VIEW: QUERY HISTORY
# ----------------------------------------------------------------------------
def view_history():
    st.markdown("<div class='viewhead'>// QUERY HISTORY</div>", unsafe_allow_html=True)
    if not st.session_state.history:
        st.info("No questions asked yet this session.")
        return
    for h in reversed(st.session_state.history):
        st.markdown(f"<div class='logline'><span class='t'>{h['t']}</span> &nbsp; {h['q']}</div>",
                    unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# Router
# ----------------------------------------------------------------------------
VIEWS = {
    "TERMINAL": view_terminal,
    "ANALYTICS": view_analytics,
    "LOGS": view_logs,
    "SENTIMENT": view_sentiment,
    "QUERY HISTORY": view_history,
}
VIEWS.get(st.session_state.view, view_terminal)()
