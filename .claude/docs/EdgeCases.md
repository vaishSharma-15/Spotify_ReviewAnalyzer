# Edge Cases — AI-Powered Review Discovery Engine

This catalog enumerates the edge cases each phase of [PhaseWiseArchitecture.md](PhaseWiseArchitecture.md) must handle gracefully. It is organized phase-by-phase, then by the cross-cutting offline/real-time boundary. Each case lists the **trigger**, the **expected behavior**, and where useful the **rationale**.

Severity legend: 🔴 must-handle (breaks correctness or the demo) · 🟡 should-handle (degrades quality) · ⚪ nice-to-have.

---

## Phase 1 — Ingestion

| # | Trigger | Expected behavior | Sev |
| --- | --- | --- | --- |
| I1 | Same review fetched twice (re-run, overlapping pages) | Dedupe via `content_hash`; never insert duplicate rows | 🔴 |
| I2 | Source returns empty `body` (rating-only app-store review) | Store row but flag as `body_empty`; Phase 2 skips or labels `other` | 🟡 |
| I3 | Non-English / mixed-language review | Persist as-is with detected `lang`; do **not** drop — handle in Phase 2 | 🔴 |
| I4 | Source API rate-limits or 5xx mid-scrape | Backoff + resume from checkpoint; partial scrape must not corrupt `reviews.db` | 🔴 |
| I5 | Missing/optional fields (no `author`, no `rating`, no `created_at`) | Insert with NULLs; never fail the row on a missing optional | 🟡 |
| I6 | Emoji-only / single-word / "👍" reviews | Persist; mark `low_signal` so Phase 2 can fast-path to `other` | 🟡 |
| I7 | Spam, ads, bot, or off-topic posts (esp. Reddit) | Persist but flag `spam_suspected`; excluded from aggregates by default | 🟡 |
| I8 | HTML/markdown/encoding artifacts in body | Normalize/clean text at ingest; preserve raw in a separate column | 🟡 |
| I9 | `source_url` missing or unstable (deleted comment) | Keep best available permalink; if none, mark `uncitable` (excluded from cited answers) | 🔴 |
| I10 | Extremely long post (Reddit wall-of-text) | Store full text; Phase 2 handles chunking/truncation, not ingestion | ⚪ |
| I11 | Schema drift from a source (API changes a field) | Fail loudly with a clear error; quarantine the batch, don't write malformed rows | 🔴 |

---

## Phase 2 — Structuring (LLM enrichment)

| # | Trigger | Expected behavior | Sev |
| --- | --- | --- | --- |
| S1 | LLM returns malformed / non-JSON output | Validate against schema; retry N times, then quarantine row (status `failed`) | 🔴 |
| S2 | LLM emits a `theme` outside the controlled vocabulary | Reject → retry with stricter prompt → coerce to `other` if still invalid | 🔴 |
| S3 | `severity_score` out of range or non-numeric | Clamp to valid range / reject; never store a non-numeric severity | 🔴 |
| S4 | Review genuinely fits no theme | Assign `other`; do not force a discovery theme (avoids inflating signal) | 🟡 |
| S5 | Review spans multiple themes equally | Pick the **dominant** theme per the taxonomy rule; nuance goes in `frustration` | 🟡 |
| S6 | Non-English review (from I3) | Translate-then-structure, or structure directly; record `lang`; never silently skip | 🔴 |
| S7 | Empty / low-signal body (from I2/I6) | Fast-path: `theme=other`, `sentiment=neutral`, `severity=0`; skip costly call | 🟡 |
| S8 | Sarcasm / negation ("oh great, *another* repeat") | Prompt must capture intent, not surface polarity; spot-check sentiment accuracy | 🟡 |
| S9 | Positive review (praise, not a frustration) | `frustration` may be null/empty; do not fabricate a pain point | 🔴 |
| S10 | No `user_segment` signal | Use `unspecified` (never guess); see [UserSegmentTaxonomy.md](UserSegmentTaxonomy.md) | 🔴 |
| S11 | Re-run after taxonomy/model version change | Idempotent on unchanged rows; re-structure only when version differs; record `model_version` | 🔴 |
| S12 | Prompt-injection text inside a review ("ignore instructions…") | Treat review body as untrusted data, never as instructions | 🔴 |
| S13 | LLM provider outage / timeout | Batch pauses and resumes; already-structured rows untouched | 🔴 |
| S14 | PII in review (names, emails) | Do not surface raw PII in stored structured fields where avoidable | 🟡 |

---

## Phase 3 — Aggregation

| # | Trigger | Expected behavior | Sev |
| --- | --- | --- | --- |
| A1 | A theme has zero reviews | Report 0 explicitly; don't drop the theme silently (absence is a signal) | 🟡 |
| A2 | Tiny sample for a theme/segment (n=2) | Show counts but flag `low_n`; query bot must caveat % claims on small n | 🔴 |
| A3 | Quarantined / spam / `uncitable` rows | Excluded from aggregate counts by default; document the exclusion rule | 🔴 |
| A4 | Multi-axis `user_segment` (review in several segments) | Count per axis separately; never sum across axes (avoids double counting) | 🔴 |
| A5 | Percentages must sum to 100% but rounding breaks it | Use consistent rounding; show raw counts alongside % | ⚪ |
| A6 | Severity skew (a few extreme scores dominate) | Report frequency **and** severity separately, plus combined rank | 🟡 |
| A7 | Source imbalance (90% Play Store, 1% forum) | Allow per-source normalization; surface source mix so claims aren't biased | 🟡 |
| A8 | Stale aggregates after DB rebuild | Aggregates regenerated atomically with the rebuild; versioned with theme/segment lists | 🔴 |

---

## Phase 4 — Indexing

| # | Trigger | Expected behavior | Sev |
| --- | --- | --- | --- |
| X1 | Embedding API fails for some rows | Retry; track unembedded rows; never serve a partially-built index as complete | 🔴 |
| X2 | Review too long for embedding model context | Chunk and store chunk→`review_id` mapping; citations resolve to parent review | 🟡 |
| X3 | Near-duplicate reviews (same complaint, many users) | Keep all (frequency is signal) but de-emphasize at retrieval to diversify evidence | 🟡 |
| X4 | Embedding model version change | Re-embed whole corpus; never mix vectors from different models in one index | 🔴 |
| X5 | `uncitable` rows (no link) reach the index | Indexable for context but flagged so they're not used as a citation | 🔴 |
| X6 | Index/DB version mismatch at serve time | Backend refuses to serve an index that doesn't match the DB build id | 🔴 |

---

## Phase 5 — Query Bot (real-time RAG)

| # | Trigger | Expected behavior | Sev |
| --- | --- | --- | --- |
| Q1 | Question outside corpus scope (e.g. "Spotify stock price") | Answer "not covered by the reviews"; never hallucinate beyond evidence | 🔴 |
| Q2 | Retrieval returns nothing relevant | Say so honestly; do not synthesize an unsupported answer | 🔴 |
| Q3 | Vague / ambiguous question ("tell me about Spotify") | Ask to narrow, or answer the closest of the six key questions with caveat | 🟡 |
| Q4 | Question implies a live/fresh scrape ("latest reviews today") | Answer from the pre-built index + state its as-of date; **never** trigger scraping | 🔴 |
| Q5 | Answer would make a % claim on low-n data | Surface the caveat / `low_n` flag rather than a confident percentage | 🔴 |
| Q6 | Every claim must be cited | Each asserted point links to ≥1 real review (source + `source_url`); drop uncitable claims | 🔴 |
| Q7 | Prompt injection in the question | Question cannot override system rules (no scraping, citation required) | 🔴 |
| Q8 | Non-English question | Answer in the question's language; citations still resolve to real reviews | ⚪ |
| Q9 | Very broad question → too many hits | Cap top-k, diversify across themes/segments, summarize with representative cites | 🟡 |
| Q10 | Duplicate evidence (same complaint cited 5×) | Deduplicate citations; show frequency as a number instead of repeating | 🟡 |
| Q11 | Contradictory reviews (praise vs complaint) | Represent both sides with cited evidence; don't cherry-pick | 🟡 |
| Q12 | Latency budget exceeded | Degrade gracefully (fewer hits) but still cite; never block on a slow call | 🟡 |

---

## Phase 6 — Deliverable Generation

| # | Trigger | Expected behavior | Sev |
| --- | --- | --- | --- |
| D1 | A key question has thin evidence in the corpus | Report the gap explicitly ("insufficient evidence for Q3") rather than padding | 🔴 |
| D2 | Identified "target segment" rests on `low_n` | State confidence level and sample size alongside the conclusion | 🔴 |
| D3 | Re-run produces different numbers (corpus grew) | Stamp the report with DB build id / as-of date for reproducibility | 🟡 |
| D4 | Two root frustrations are near-tied in rank | Report both with their scores; don't force a single winner | ⚪ |

---

## Cross-Cutting: Offline / Real-Time Boundary

| # | Trigger | Expected behavior | Sev |
| --- | --- | --- | --- |
| C1 | Query path attempts to scrape | Architecturally impossible: serving layer has no scraper dependency | 🔴 |
| C2 | DB rebuild happens while API is serving | Atomic swap / versioned artifact; in-flight queries finish on the old build | 🔴 |
| C3 | Backend boots with missing/corrupt `reviews.db` | Fail health check; refuse traffic rather than serve empty/garbage answers | 🔴 |
| C4 | Empty corpus (fresh DB, nothing ingested yet) | API returns a clear "no data yet" state; frontend shows it, doesn't error | 🔴 |
| C5 | Partial pipeline (ingested but not structured/indexed) | Serve only what's complete, or block promotion; never serve a half-built artifact | 🔴 |
| C6 | Concurrent on-demand scrape + scheduled scrape | Single-flight / lock so two pipelines don't write the same DB simultaneously | 🟡 |
| C7 | Secrets (LLM/embedding keys) missing at deploy | Fail fast with a clear config error; never silently degrade | 🟡 |
| C8 | Source mix changes the corpus shape between builds | Aggregates and report note the as-of source distribution | ⚪ |
