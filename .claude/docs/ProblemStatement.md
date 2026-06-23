# AI-Powered Review Discovery Engine

## Problem Statement

Spotify has acquired millions of users and built one of the world's most sophisticated recommendation systems. Despite this, a significant share of listening still comes from repeat playlists, familiar artists, and previously discovered tracks. A strategic goal for the company is to **increase meaningful music discovery and reduce repetitive listening behavior**.

Before proposing any solution, we must understand the problem at scale through real user feedback. **Part 1** requires an AI-powered system that ingests and analyzes user feedback from multiple public sources and surfaces evidence-backed insight into why discovery breaks down.

This engine is an **insight tool** — it is distinct from any product feature built later. It must help answer questions such as:

- Why do users struggle to discover new music?
- What are the most common frustrations with recommendations?
- What listening behaviors are users trying to achieve?
- What causes users to repeatedly listen to the same content?
- Which user segments experience different discovery challenges?
- What unmet needs emerge consistently across reviews?

## Expected Behavior

The engine should ingest user feedback from the **Google Play Store**, **Apple App Store**, **Reddit** (`r/spotify`, `r/truespotify` — posts and comments), and the **Spotify Community forum**. The ingestion pipeline already exists and writes all reviews into a real datastore (`reviews.db`); the engine reads from that store and does not reload data from any flat CSV file.

- **Structure feedback at scale.** Pass each review through an LLM that returns a fixed schema — theme, sentiment, job-to-be-done, the specific frustration, a user-segment signal, the feature mentioned, and a severity score — turning unstructured text into queryable data.

- **Quantify the patterns.** Aggregate the structured fields to show theme distribution, the most common frustrations ranked by frequency and severity, sentiment by theme, and a breakdown by user segment, so claims are backed by numbers (e.g. "X% of discovery complaints cluster into three root frustrations").

- **Answer questions with evidence.** A user can ask any of the questions above in natural language and receive a synthesized answer that retrieves and cites real supporting reviews, with their source and link — not a generic summary.

- **Respond in real time, robustly.** Querying never triggers live scraping. Scraping happens offline (and can be triggered on demand to prove the pipeline is live), while the bot answers instantly from a pre-built index, so a demo never depends on a scrape succeeding mid-conversation.

- **Produce the Part 1 deliverable.** Running the engine against the six key questions yields a set of evidence-backed answers that identify the target segment and root frustrations — the input for validation interviews and problem definition in the next stages.
