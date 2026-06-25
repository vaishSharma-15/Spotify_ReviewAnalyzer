# 🟢 Spotify Review Discovery Engine

An **AI-powered review discovery engine** that ingests, structures, and analyzes
public Spotify user feedback to surface **evidence-backed insights about why music
discovery fails** for users.

This is an **insight tool**, not a product feature. You ask a natural-language
question; it answers by analyzing thousands of real user reviews — instantly,
from a pre-built index, grounded in actual complaints.

> **Live demo:** a Streamlit chat app where you ask questions and watch the
> backend pipeline run in real time in the sidebar.

---

## 🎯 What it answers

The engine is designed backward from six key questions:

1. Why do users struggle to discover new music?
2. What are the most common frustrations with recommendations?
3. What listening behaviors are users trying to achieve?
4. What causes users to repeatedly listen to the same content?
5. Which user segments experience different discovery challenges?
6. What unmet needs emerge consistently across reviews?

If you ask something off-topic, it politely says it only covers music discovery.

---

## 🧭 How it works (architecture)

The system splits into an **offline pipeline** (built ahead of time) and a
**real-time query bot** (answers instantly).

```
OFFLINE (build once)                          REAL-TIME (per question)
┌─────────────┐  ┌─────────────┐  ┌──────────┐   ┌─────────────────────┐
│ ① Ingestion │→ │② Structuring│→ │③ Aggreg. │   │ ⑤ Query bot (RAG)   │
│  scrape 5   │  │  Groq LLM   │  │ theme /  │   │ embed question →    │
│  sources    │  │  labels each│  │ sentiment│   │ vector search →     │
└─────────────┘  │  review     │  │ stats    │   │ pull top reviews →  │
                 └─────────────┘  └──────────┘   │ + aggregates →      │
                 ┌─────────────┐                 │ Groq writes answer  │
                 │ ④ Indexing  │ ───────────────▶│                     │
                 │ embed +     │   pre-built     └─────────────────────┘
                 │ Chroma store│   index
                 └─────────────┘
```

**Key design constraints**
- Queries are **instant** — answers come from a pre-built index, never live scraping.
- All data lives in **`reviews.db`** (SQLite) — the single source of truth.
- Every answer is grounded in **real reviews** that were actually retrieved.

---

## 📊 The data pipeline (review funnel)

| Stage | Count | What happened |
|---|---|---|
| **Extracted** (raw scrape) | ~5,952 | Pulled from 5 public sources |
| **Filtered** (theme-relevant) | ~1,919 | Kept only reviews about discovery themes |
| **Curated** | **1,659** | Removed emojis + positive reviews → negative, on-theme only |
| **Structured** (Groq LLM) | 1,000+ | Labeled with theme / sentiment / segment / severity |
| **Indexed** (Chroma) | 1,000+ | Embedded into a searchable vector store |

**Sources** (current curated set): `social` (1,269), `app_store` (182),
`play_store` (156), `community_forum` (36), `reddit` (16).

> The App Store (iTunes RSS) and Play Store (`google-play-scraper`) collectors
> work without credentials. Reddit and the Community forum need auth/OAuth for
> reliable access; collectors **degrade gracefully** and skip a source if its
> dependency or credentials are missing.

---

## 🗂️ Project structure

```
ingestion/              # Phase 1 — scrape sources → raw_reviews
  collectors/           #   appstore, playstore, reddit, community, social
  base.py               #   RawReview model, dedup by content_hash, text cleaning
  db.py                 #   SQLite store (reviews.db)
  run.py                #   CLI orchestrator
  filter_relevance.py   #   keep theme-relevant reviews
  curate.py             #   strip emojis, drop positives, tag themes
structuring/            # Phase 2 — LLM labels each review (controlled vocab)
  schema.py             #   themes, segments, sentiments, prompt, model
  structure.py          #   idempotent batch runner (rate-limit aware)
aggregation/            # Phase 3 — theme/sentiment/segment stats (agg_* tables)
indexing/               # Phase 4 — embed + build Chroma vector index
  embed.py              #   all-MiniLM-L6-v2 (384-dim, local)
  build_index.py        #   Chroma persistent store
app/                    # Phase 5 — query bot
  rag.py                #   retrieve + aggregates + Groq synthesis
  main.py               #   FastAPI backend (local/dev)
  static/index.html     #   chat UI
streamlit_app.py        # Combined frontend+backend (deployable)
reviews.db              # SQLite — single source of truth
chroma_index/           # pre-built vector index
.claude/docs/           # ProblemStatement, PhaseWiseArchitecture, taxonomies, edge cases
```

---

## 🧠 Tech stack

| Layer | Choice |
|---|---|
| **LLM (structuring + answers)** | [Groq](https://groq.com) — `llama-3.1-8b-instant` (OpenAI-compatible API) |
| **Embeddings** | `sentence-transformers/all-MiniLM-L6-v2` (384-dim, runs locally) |
| **Vector store** | [Chroma](https://www.trychroma.com) (persistent, cosine similarity) |
| **Datastore** | SQLite (`reviews.db`) |
| **Backend** | FastAPI (dev) / Streamlit (deployed) |
| **Frontend** | Streamlit chat UI (Spotify dark theme) |

---

## 🚀 Getting started

### 1. Install
```bash
pip install -r requirements.txt
```

### 2. Set your API key
Create a `.env` file (see `.env.example`):
```bash
GROQ_API_KEY=your_groq_key_here
```
> Get a free key at [console.groq.com](https://console.groq.com).

### 3. Run the app
```bash
streamlit run streamlit_app.py
```
The repo ships with a pre-built `reviews.db` + `chroma_index/`, so the chatbot
works out of the box — no need to re-run the pipeline.

---

## 🔧 Rebuilding the pipeline (optional)

Each phase has a CLI. Run them in order to rebuild from scratch:

```bash
# Phase 1 — ingest reviews
python3 -m ingestion.run --all --limit 200      # scrape every source
python3 -m ingestion.run --status               # show DB counts

# Phase 2 — structure with the LLM
python3 -m structuring.structure --all          # process pending reviews
python3 -m structuring.structure --status       # progress + theme distribution

# Phase 3 — aggregate
python3 -m aggregation.aggregate

# Phase 4 — build the vector index
python3 -m indexing.build_index
```

> **Groq free-tier note:** structuring is rate-limited (daily token cap). The
> runner is **idempotent** — it processes what it can, leaves the rest `pending`,
> and you can re-run it the next day to finish.

---

## ☁️ Deployment (Streamlit Community Cloud)

1. Push the repo to GitHub.
2. Create an app at [share.streamlit.io](https://share.streamlit.io) pointing at
   `streamlit_app.py`.
3. In **Settings → Secrets**, add:
   ```toml
   GROQ_API_KEY = "your_groq_key"
   ```
4. **Python version:** set to **3.11** (the committed Chroma index was built with
   `chromadb==0.6.3`, pinned in `requirements.txt`; newer Chroma can't read it).

The app redeploys automatically on every push to `main`.

---

## 📡 Live activity panel

To show the pipeline is a **real workflow** (not a static dataset), the sidebar
streams the actual backend stages for every question in real time:

```
🔎 Reading your question…
🧬 Turned it into a 384-dim meaning vector (… ms)
📚 Searched all 1000 indexed reviews → reading the 12 most relevant ones (… ms)
📊 Loaded stats over 1,000 analyzed reviews
🏷️ Main themes in these reviews: discovery friction, recommendation relevance…
🤖 Asking the Groq LLM to summarize 12 reviews into one answer…
✅ Answer ready — built from 12 reviews (… ms)
```

---

## 📚 Documentation

Deeper design docs live in [`.claude/docs/`](.claude/docs/):
- **ProblemStatement.md** — the problem and the six key questions
- **PhaseWiseArchitecture.md** — full phase-by-phase spec + deployment plan
- **ThemeTaxonomy.md** / **UserSegmentTaxonomy.md** — controlled vocabularies
- **EdgeCases.md** — edge-case catalog

---

## ⚠️ Notes & limitations

- The chatbot focuses on **negative** reviews by default — it's a *frustration
  discovery* tool, so positive feedback is excluded unless asked for.
- Answers reflect **public reviews only**; they're directional signal, not a
  statistically representative survey of all Spotify users.
- Re-running ingestion is a **no-op for existing rows** (dedup by `content_hash`).
