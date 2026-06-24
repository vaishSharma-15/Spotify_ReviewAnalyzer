# User Segment Taxonomy — Spotify Review Discovery Engine

This is the **controlled vocabulary** for the `user_segment` field produced in Phase 2 (Structuring). It exists so **Q5 — "Which user segments experience different discovery challenges?"** can be answered by slicing every theme (see [ThemeTaxonomy.md](ThemeTaxonomy.md)) by a clean, fixed set of segment values.

Rules for the LLM:
- A review may map to **one or more** segments (segments are not mutually exclusive — e.g. a review can be both `premium` and `power_user`).
- Use the `id` value(s) verbatim; never invent free-text variants.
- Infer the segment only from explicit or strongly-implied signals in the review. If there is no signal, use `unspecified`.

---

## Segment Axes

Segments fall along three independent axes. A review can carry one value from each axis where signal exists.

### Axis 1 — Engagement level (how heavily they use Spotify)

| `id` | Definition | Example signals |
| --- | --- | --- |
| `power_user` | Heavy, daily user who curates playlists, explores deeply | "I make playlists constantly", "10 years, all day" |
| `casual_listener` | Occasional, passive listener; hits play and lets it run | "just put it on in the background", "use it now and then" |
| `new_user` | Recently signed up; cold-start / onboarding stage | "just downloaded", "first week", "new to Spotify" |
| `returning_user` | Came back after a lapse or switched from another service | "back after a year", "switched from Apple Music" |

### Axis 2 — Plan / tier

| `id` | Definition | Example signals |
| --- | --- | --- |
| `free_tier` | Ad-supported free user | "the ads", "can't skip", "free version" |
| `premium` | Paying individual subscriber | "I pay for premium", "premium and still…" |
| `family_plan` | Family / Duo plan; shared-account discovery effects | "family plan", "kids mess up my recs" |
| `student_plan` | Student subscription | "student discount", "as a student" |

### Axis 3 — Listening identity (who they are as a listener)

| `id` | Definition | Example signals |
| --- | --- | --- |
| `music_explorer` | Actively wants novelty / new artists & genres | "love finding new artists", "want fresh music" |
| `genre_specialist` | Devoted to specific genre(s) / niche taste | "I only listen to jazz", "metal fan", "K-pop" |
| `mood_context_listener` | Listens by activity/mood (focus, workout, sleep, commute) | "for the gym", "study playlists", "sleep sounds" |
| `podcast_audiobook_user` | Primarily spoken-word content | "mostly podcasts", "audiobooks" |
| `artist_creator` | Artist / creator perspective on the platform | "as an artist", "my releases" |

### Fallback

| `id` | Definition |
| --- | --- |
| `unspecified` | No reliable segment signal in the review |

---

## Notes for Aggregation (Phase 3)

- **Q5** is answered by cross-tabbing `theme` × `user_segment` and comparing where pain concentrates (e.g. *"`new_user` reviews skew heavily to `onboarding_taste_profile`, while `power_user` reviews skew to `filter_bubble`"*).
- Because segments are multi-axis, a single review can contribute to multiple segment slices — counts per axis should be reported separately, not summed across axes.
- Keep this list **versioned together with** the `theme` list; changing either invalidates cached aggregates.
