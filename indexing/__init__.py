"""Phase 4 — Indexing (retrieval store).

Embeds structured reviews into a vector index (a sidecar table in reviews.db)
so the Phase 5 query bot can retrieve relevant reviews by meaning, instantly,
without ever re-scraping. See .claude/docs/PhaseWiseArchitecture.md.
"""

from .embed import EMBED_MODEL, embed_texts, load_model

__all__ = ["EMBED_MODEL", "embed_texts", "load_model"]
