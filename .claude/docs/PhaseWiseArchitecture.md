# Phase-Wise Architecture — AI-Powered Review Discovery Engine

This document breaks the [ProblemStatement.md](ProblemStatement.md) into a phased architecture. Each phase has a clear input, output, and boundary so the offline pipeline (scraping → structuring → indexing) stays fully decoupled from the real-time query path.

## Architecture Overview

```
            OFFLINE PIPELINE (decoupled, on-demand)                 REAL-TIME PATH
 ┌───────────────────────────────────────────────────────┐   ┌────────────────────────┐
 │                                                         │   │                        │
 │  Phase 1        Phase 2         Phase 3       Phase 4   │   │  Phase 5      Phase 6  │
 │  Ingestion  →   Structuring →   Aggregation → Indexing  │   │  Query Bot →  Deliver- │
 │  (exists)       (LLM schema)    (analytics)  (vectors)  │   │  (RAG)        able     │
 │      │              │               │            │      │   │     │            │      │
 └──────┼──────────────┼───────────────┼────────────┼──────┘   └─────┼────────────┼──────┘
        ▼              ▼               ▼            ▼               ▼            ▼
   ┌──────────────────────────────────────────────────────────────────────────────────┐
   │                              reviews.db  (SQLite — single source of truth)         │
   │   raw_reviews │ structured_reviews │ aggregates │ vector_index (or sidecar store)  │
   └──────────────────────────────────────────────────────────────────────────────────┘
```

**Key boundary:** Phases 1–4 run offline and can be triggered on demand to prove the pipeline is live. Phases 5–6 read only from the pre-built data in `reviews.db` and **never trigger live scraping**.

---

## Phase 1 — Ingestion (already exists)

**Goal:** Collect raw user feedback from all public sources into the datastore.

| Aspect | Detail |
| --- | --- |
| **Sources** | Google Play Store, Apple App Store, Reddit (`r/spotify`, `r/truespotify` — posts & comments), Spotify Community forum |
| **Input** | Public review/post/comment APIs and scrapers |
| **Output** | `raw_reviews` table in `reviews.db` |
| **Trigger** | Offline; can be invoked on demand to demonstrate the live pipeline |

**`raw_reviews` (suggested schema):**
- `id` (PK) · `source` · `source_url` · `author` · `created_at`
- `rating` (nullable — app stores only) · `title` (nullable) · `body`
- `ingested_at` · `content_hash` (for dedup)

**Responsibilities:** normalize fields across heterogeneous sources, deduplicate via `content_hash`, preserve the original `source_url` so later phases can cite it.

---

## Phase 2 — Structuring (LLM enrichment)

**Goal:** Turn each unstructured review into queryable, fixed-schema data.

Each `raw_review` is passed through an LLM that returns a **fixed schema**:

| Field | Description |
| --- | --- |
| `theme` | High-level topic (e.g. *discovery*, *recommendations*, *playback*) |
| `sentiment` | `positive` / `neutral` / `negative` |
| `job_to_be_done` | What the user was trying to accomplish |
| `frustration` | The specific pain point expressed |
| `user_segment` | Signal about the type of user (e.g. *power user*, *casual listener*) |
| `feature_mentioned` | Spotify feature referenced |
| `severity_score` | Numeric weight of the complaint (e.g. 1–5) |

| Aspect | Detail |
| --- | --- |
| **Input** | `raw_reviews` rows not yet structured |
| **Output** | `structured_reviews` table (1:1 with `raw_reviews`, FK on `review_id`) |
| **Design** | Batch processing, idempotent (skip already-structured rows), strict schema validation, controlled vocabulary for `theme`/`user_segment` to keep aggregation clean |

**Robustness:** use structured output / JSON-mode with validation; on malformed output, retry then quarantine. Store the model version so re-runs are auditable.

---

## Phase 3 — Aggregation (analytics)

**Goal:** Quantify the patterns so every claim is backed by numbers.

| Aspect | Detail |
| --- | --- |
| **Input** | `structured_reviews` |
| **Output** | `aggregates` (materialized tables/views) |
| **Metrics** | Theme distribution · top frustrations ranked by frequency **and** severity · sentiment by theme · breakdown by user segment |

**Example output:** *"X% of discovery complaints cluster into three root frustrations."* These aggregates are precomputed so the query bot can quote numbers instantly without scanning the full table at query time.

---

## Phase 4 — Indexing (retrieval store)

**Goal:** Build the pre-built index that powers instant, evidence-cited retrieval.

| Aspect | Detail |
| --- | --- |
| **Input** | `structured_reviews` (+ raw text for citation) |
| **Output** | Vector index + metadata (embeddings stored in `reviews.db` as a sidecar table, or an embedded vector store) |
| **Indexed payload** | `review_id`, embedding, `theme`, `sentiment`, `user_segment`, `source`, `source_url`, original text |

This is the boundary that guarantees real-time response: retrieval hits a pre-built index, **never a live scrape**. Metadata is carried into the index so the bot can filter (e.g. by theme/segment) and cite source + link directly from a retrieval hit.

---

## Phase 5 — Query Bot (RAG, real-time)

**Goal:** Answer natural-language questions with synthesized, evidence-cited responses.

**Flow:**
1. User asks a question in natural language.
2. Embed the query → retrieve top-k relevant reviews from the Phase 4 index (with optional metadata filters).
3. Pull matching Phase 3 aggregates to ground the answer in numbers.
4. LLM synthesizes an answer that **cites real reviews with source and link** — not a generic summary.

| Aspect | Detail |
| --- | --- |
| **Input** | NL question + pre-built index + aggregates |
| **Output** | Synthesized answer with inline citations (source + `source_url`) |
| **Constraints** | Instant response; no live scraping; every claim traceable to retrieved reviews |

---

## Phase 6 — Deliverable Generation

**Goal:** Produce the Part 1 deliverable.

Run the engine against the **six key questions** from the problem statement and emit a set of evidence-backed answers that identify the **target segment** and **root frustrations** — the input for validation interviews and problem definition in later stages.

| Aspect | Detail |
| --- | --- |
| **Input** | The six key questions (Phase 5 over the full index) |
| **Output** | A structured report: per-question answer + supporting cited reviews + quantified backing |
| **Audience** | Next-stage validation interviews and problem definition |

---

## Phase Dependency Summary

| Phase | Depends on | Runtime | Writes |
| --- | --- | --- | --- |
| 1 Ingestion | — | Offline / on-demand | `raw_reviews` |
| 2 Structuring | Phase 1 | Offline batch | `structured_reviews` |
| 3 Aggregation | Phase 2 | Offline batch | `aggregates` |
| 4 Indexing | Phase 2 | Offline batch | `vector_index` |
| 5 Query Bot | Phases 3 + 4 | Real-time | — (read-only) |
| 6 Deliverable | Phase 5 | On-demand | report artifact |

---

## Deployment Plan

The same offline/real-time boundary maps cleanly onto deployment: the **offline pipeline** runs as scheduled/on-demand jobs, the **backend API** serves the real-time query path, and the **frontend** is a thin client that only talks to the API. `reviews.db` (with its embeddings) is the artifact handed from the pipeline to the API.

```
   ┌────────────┐      HTTPS / JSON      ┌──────────────────────┐
   │  Frontend  │ ───────────────────▶   │   Backend API        │
   │  (SPA)     │ ◀───────────────────   │   (FastAPI)          │
   └────────────┘   answers + citations  │   Phase 5 RAG        │
                                         │   Phase 3 aggregates │
                                         └──────────┬───────────┘
                                                    │ read-only
                                                    ▼
                                         ┌──────────────────────┐
                                         │   reviews.db          │  ◀── built by
                                         │   + vector index      │      offline jobs
                                         └──────────────────────┘      (Phases 1–4)
```

### Backend Deployment

| Aspect | Detail |
| --- | --- |
| **Stack** | Python API (FastAPI + Uvicorn/Gunicorn) wrapping Phase 5 (RAG) and read endpoints over Phase 3 aggregates |
| **Packaging** | Docker image; `reviews.db` baked into the image **or** mounted from a persistent volume / object store at startup |
| **Endpoints** | `POST /query` (NL question → cited answer), `GET /aggregates/*` (theme distribution, top frustrations, sentiment-by-theme, segment breakdown), `GET /health` |
| **Hosting** | Container platform — Render / Railway / Fly.io / AWS ECS / Cloud Run. Start single-instance; scale horizontally since the API is stateless (DB is read-only) |
| **Secrets** | LLM + embedding API keys via environment variables / secrets manager — never in the image |
| **Scaling note** | The DB is read-only at serve time, so replicas can share the same artifact freely; no write contention |

### Frontend Deployment

| Aspect | Detail |
| --- | --- |
| **Stack** | SPA (React/Next.js or similar) — chat-style UI for asking the six key questions and free-form queries, plus dashboards rendering the aggregates |
| **Build** | Static build (`npm run build`) served via CDN |
| **Hosting** | Vercel / Netlify / Cloudflare Pages / S3 + CloudFront |
| **Config** | `API_BASE_URL` injected at build/runtime; CORS allowlist set on the backend for the frontend origin |
| **Responsibilities** | Render answers **with their citations** (source + link), show aggregate charts, expose a "trigger scrape" admin action that calls the pipeline endpoint (clearly separated from the read path) |

### Offline Pipeline Deployment (Phases 1–4)

| Aspect | Detail |
| --- | --- |
| **Execution** | Scheduled job (cron / GitHub Actions / cloud scheduler) **and** an on-demand trigger to prove the pipeline is live during a demo |
| **Output** | A freshly rebuilt `reviews.db` (raw → structured → aggregates → vector index) |
| **Handoff** | Publish the rebuilt DB to a volume / object store (e.g. S3); the backend picks up the new artifact on deploy or via a reload signal |
| **Isolation** | Runs entirely separate from the serving containers so scraping/LLM batch load never affects query latency |

### Environments & Release Flow

| Environment | Purpose |
| --- | --- |
| **Local** | Run pipeline once to build `reviews.db`, then run API + frontend against it |
| **Staging** | Validate a freshly built DB artifact end-to-end before promotion |
| **Production** | Stable API + frontend serving the latest promoted `reviews.db` |

**Release flow:** offline pipeline builds & validates `reviews.db` → artifact promoted to staging → smoke-test the six key questions → promote artifact to production → backend reloads the new DB → frontend (independently deployed) continues pointing at the same API. Frontend and backend deploy independently; the DB artifact is versioned so a bad rebuild can be rolled back without redeploying code.
