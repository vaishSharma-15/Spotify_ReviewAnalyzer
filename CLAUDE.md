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

**Ingestion pipeline** — scrapes sources and writes to `reviews.db`. This can be triggered on demand to prove the pipeline is live, but runs offline from the query bot.

**Structuring layer** — passes each review through an LLM and returns a fixed schema per review:
- `theme` — high-level topic category
- `sentiment` — positive / neutral / negative
- `job_to_be_done` — what the user was trying to accomplish
- `frustration` — specific pain point expressed
- `user_segment` — signal about the type of user
- `feature_mentioned` — Spotify feature referenced
- `severity_score` — numeric weight of the complaint

**Aggregation layer** — computes: theme distribution, top frustrations ranked by frequency and severity, sentiment by theme, breakdown by user segment.

**Query bot** — accepts natural-language questions, retrieves supporting reviews from `reviews.db` (pre-built index), and returns a synthesized answer that cites real reviews with source and link. Responds instantly; never triggers a live scrape.

## Key Design Constraints

- Queries must be instant — answers come from a pre-built index, not live scraping
- Structured data lives in `reviews.db`; never reload from CSV
- Every claim in an answer must be backed by cited reviews (source + link)
- The six key questions in the problem statement (see [.claude/docs/ProblemStatement.md](.claude/docs/ProblemStatement.md)) are the primary deliverable to answer
