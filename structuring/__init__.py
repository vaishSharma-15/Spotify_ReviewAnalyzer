"""Phase 2 — Structuring (LLM enrichment).

Passes each raw_review through Claude and returns a fixed schema, writing the
result to the structured_reviews table (1:1 with raw_reviews). Idempotent,
batch-oriented, schema-validated; see .claude/docs/PhaseWiseArchitecture.md.
"""

__all__ = ["SCHEMA", "THEMES", "USER_SEGMENTS", "MODEL"]

from .schema import MODEL, SCHEMA, THEMES, USER_SEGMENTS
