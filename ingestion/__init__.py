"""Phase 1 — Ingestion.

Collects raw Spotify user feedback from multiple public sources and writes
normalized rows into reviews.db (the single source of truth). This package is
the offline pipeline described in .claude/docs/PhaseWiseArchitecture.md; it runs
on demand and is fully decoupled from the real-time query path.
"""

__all__ = ["RawReview", "ReviewStore"]

from .base import RawReview
from .db import ReviewStore
