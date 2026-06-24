# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

This is an **AI-powered review discovery engine** for Spotify. The goal is to ingest, structure, and analyze user feedback from public sources to surface evidence-backed insights about why music discovery fails for users.

This is an **insight tool** (not a product feature). It answers questions like:
- Why do users struggle to discover new music?
- What are the most common frustrations with recommendations?
- What causes repetitive listening behavior?
- Which user segments face different discovery challenges?

## Data Sources

User feedback is ingested from:
- Google Play Store reviews
- Apple App Store reviews
- Reddit (`r/spotify`, `r/truespotify` — posts and comments)
- Spotify Community forum

All reviews are stored in **`reviews.db`** (SQLite). The engine reads from this datastore exclusively — never from flat CSV files, and never triggers live scraping during a query.

## Core Architecture (to build)

**Ingestion pipeline** (Phase 1 — implemented in [ingestion/](ingestion/)) — scrapes sources and writes normalized rows to the `raw_reviews` table in `reviews.db`. Runs on demand, fully decoupled from the query bot.

Each source is a pluggable `BaseCollector` ([ingestion/collectors/](ingestion/collectors/)) that **degrades gracefully** — if its optional dependency or credentials are missing, the orchestrator skips it and keeps going. Dedup is by `content_hash` (re-running is a no-op for existing rows).

```bash
pip install -r requirements.txt          # optional deps per source; App Store needs none
python3 -m ingestion.run --all --limit 200          # collect from every source
python3 -m ingestion.run --source app_store --limit 60   # one source
python3 -m ingestion.run --status                   # show DB counts by source
```

Source status: **App Store** (iTunes RSS) and **Play Store** (`google-play-scraper`) work without credentials. **Reddit** and **Community forum** public endpoints are anti-bot blocked (403) — Reddit needs OAuth creds via `praw` (`REDDIT_*` in `.env`); the forum needs authenticated/Khoros-API access. **Social** (X/Twitter) requires `TWITTER_BEARER_TOKEN`. See [.env.example](.env.example).

**Structuring layer** — passes each review through an LLM and returns a fixed schema per review:
- `theme` — high-level topic category (controlled vocabulary — see [.claude/docs/ThemeTaxonomy.md](.claude/docs/ThemeTaxonomy.md))
- `sentiment` — positive / neutral / negative
- `job_to_be_done` — what the user was trying to accomplish
- `frustration` — specific pain point expressed
- `user_segment` — signal about the type of user (controlled vocabulary — see [.claude/docs/UserSegmentTaxonomy.md](.claude/docs/UserSegmentTaxonomy.md))
- `feature_mentioned` — Spotify feature referenced
- `severity_score` — numeric weight of the complaint

The `theme` and `user_segment` fields **must** use the controlled vocabularies (no free-text variants) so aggregation stays clean. Both taxonomies are designed backward from the six key questions and are versioned together — changing either invalidates cached aggregates.

**Aggregation layer** — computes: theme distribution, top frustrations ranked by frequency and severity, sentiment by theme, breakdown by user segment.

**Query bot** — accepts natural-language questions, retrieves supporting reviews from `reviews.db` (pre-built index), and returns a synthesized answer that cites real reviews with source and link. Responds instantly; never triggers a live scrape.

## Key Design Constraints

- Queries must be instant — answers come from a pre-built index, not live scraping
- Structured data lives in `reviews.db`; never reload from CSV
- Every claim in an answer must be backed by cited reviews (source + link)
- The six key questions in the problem statement (see [.claude/docs/ProblemStatement.md](.claude/docs/ProblemStatement.md)) are the primary deliverable to answer
