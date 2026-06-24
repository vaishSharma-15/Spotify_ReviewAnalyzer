# Theme Taxonomy — Spotify Review Discovery Engine

This is the **controlled vocabulary** for the `theme` field produced in Phase 2 (Structuring). Themes are deliberately designed so that aggregating on them (Phase 3) and retrieving by them (Phase 4/5) can answer the **six key questions** from [ProblemStatement.md](ProblemStatement.md).

Rules for the LLM:
- Assign **exactly one** `theme` per review from the list below (the dominant topic).
- Use the `id` value verbatim — no free-text variants — so aggregation stays clean.
- A review's nuance (the *why*) lives in `frustration` / `job_to_be_done`; `theme` is just the bucket.

---

## The Six Questions → Themes Map

| # | Key Question | Primary themes that answer it |
| --- | --- | --- |
| Q1 | Why do users struggle to discover new music? | `discovery_friction`, `findability_search`, `catalog_availability`, `onboarding_taste_profile` |
| Q2 | What are the most common frustrations with recommendations? | `recommendation_relevance`, `recommendation_repetition`, `personalization_control` |
| Q3 | What listening behaviors are users trying to achieve? | `listening_context`, `library_playlist_mgmt` (read via `job_to_be_done`) |
| Q4 | What causes users to repeatedly listen to the same content? | `recommendation_repetition`, `filter_bubble`, `recommendation_relevance` |
| Q5 | Which user segments experience different discovery challenges? | *all themes, sliced by* `user_segment` |
| Q6 | What unmet needs emerge consistently across reviews? | *all themes, ranked by* `frustration` + `severity_score` |

> Q5 and Q6 are **cross-cutting** — they are answered by slicing/ranking every theme by `user_segment`, `frustration`, and `severity_score` rather than by a dedicated theme.

---

## Theme Definitions

### Discovery-core themes

| `id` | Label | Definition | Example signals |
| --- | --- | --- | --- |
| `discovery_friction` | Discovery friction | General difficulty finding *new* music; discovery feels hard, hidden, or absent | "I never find new songs", "discovery is buried", "feels stuck" |
| `recommendation_relevance` | Recommendation relevance | Recommendations are inaccurate, generic, or don't match taste | "recs are way off", "suggests stuff I hate", "not for me" |
| `recommendation_repetition` | Recommendation repetition | Recs / autoplay / radio keep surfacing the *same* tracks & artists | "same 30 songs", "loops the same playlist", "always the hits" |
| `filter_bubble` | Filter bubble / echo chamber | Algorithm over-narrows to past taste; no novelty or serendipity | "only shows what I already listen to", "stuck in a bubble" |
| `personalization_control` | Personalization control | Wanting to steer/correct the algorithm (dislike, "not interested", seed control) | "can't tell it to stop", "no way to reset taste", "wish I could exclude" |
| `findability_search` | Findability & search | Search / browse / navigation makes it hard to locate music or discovery surfaces | "search is bad", "can't find the radio", "buried in menus" |
| `catalog_availability` | Catalog & availability | Desired music, genres, or regional content missing from the catalog | "song not available", "my region lacks…", "no podcasts of X" |
| `onboarding_taste_profile` | Onboarding & taste profiling | Cold-start / taste setup; new users get poor early discovery | "new account, bad recs", "never asked my taste" |
| `new_release_artist_discovery` | New release & artist discovery | Surfacing new/emerging artists, releases, and deep cuts | "miss new releases", "only big artists", "never see indie" |
| `social_sharing_discovery` | Social & sharing discovery | Discovering via friends, shared playlists, social signals | "want friend activity back", "hard to share/find from others" |

### Behavior & context themes

| `id` | Label | Definition | Example signals |
| --- | --- | --- | --- |
| `listening_context` | Listening context / mood | Use-case-driven listening: focus, workout, sleep, commute, party, mood | "need focus playlists", "workout mix is stale", "good for sleep" |
| `library_playlist_mgmt` | Library & playlist management | Organizing, saving, curating one's own library & playlists | "can't sort", "playlist got messed up", "hard to manage saves" |

### Cross-cutting / non-discovery catch-alls

These keep the taxonomy exhaustive so non-discovery reviews don't pollute the core themes. They are tracked but are **not** the deliverable's focus.

| `id` | Label | Definition |
| --- | --- | --- |
| `playback_quality` | Playback & audio quality | Streaming quality, shuffle behavior, gapless, offline playback |
| `app_performance` | App performance & bugs | Crashes, slowness, sync issues, UI bugs |
| `pricing_subscription` | Pricing & subscription | Cost, plans, family/student, billing |
| `ads_experience` | Ads experience | Ad frequency/relevance on free tier |
| `account_access` | Account & access | Login, devices, account management |
| `other` | Other | Doesn't fit any theme above (use sparingly) |

---

## Notes for Aggregation (Phase 3)

- **Q4 (repetition)** is best shown as a cluster: combine `recommendation_repetition` + `filter_bubble` + low-novelty mentions in `recommendation_relevance` to quantify *"X% of discovery complaints trace to the algorithm over-narrowing."*
- **Q5 (segments)** = every theme grouped by `user_segment` (e.g. *power user* vs *casual listener* vs *new user*) to expose differing pain.
- **Q6 (unmet needs)** = top `frustration` strings ranked by frequency × mean `severity_score`, reported per theme.
- Keep the controlled `theme` list and the controlled `user_segment` list versioned together; changing either invalidates cached aggregates.
