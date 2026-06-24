"""Normalized review model + collector base class.

Every collector, regardless of source, produces ``RawReview`` instances. This
keeps the heterogeneous sources (app stores, Reddit, forum, social) behind one
uniform shape so the DB layer and later phases never special-case a source.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator, Optional

# Controlled set of source identifiers. Stored verbatim in raw_reviews.source
# so aggregation (Phase 3) can slice by source without string drift.
SOURCES = (
    "play_store",
    "app_store",
    "reddit",
    "community_forum",
    "social",
)

_WS_RE = re.compile(r"\s+")


def clean_text(text: Optional[str]) -> str:
    """Normalize whitespace/encoding while preserving the human-readable body.

    The raw, untouched text should be kept by the collector if it needs the
    original; this returns the cleaned version used for hashing and storage.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\x00", "")
    text = _WS_RE.sub(" ", text)
    return text.strip()


def content_hash(source: str, body: str, author: Optional[str]) -> str:
    """Stable dedup key (edge case I1). Same complaint from the same author on
    the same source hashes identically across re-runs, so re-ingesting is a
    no-op rather than a duplicate insert."""
    basis = f"{source}\x1f{clean_text(body).lower()}\x1f{(author or '').lower()}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def to_iso(value) -> Optional[str]:
    """Coerce assorted timestamp shapes to ISO-8601 UTC, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    if isinstance(value, (int, float)):  # epoch seconds
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    if isinstance(value, str):
        return value  # assume already a parseable string; stored as-is
    return None


@dataclass
class RawReview:
    """One unit of user feedback, normalized across sources."""

    source: str
    source_url: Optional[str]
    body: str
    author: Optional[str] = None
    title: Optional[str] = None
    rating: Optional[int] = None          # app stores only; None elsewhere
    created_at: Optional[str] = None       # ISO-8601 UTC
    lang: Optional[str] = None             # best-effort; None if unknown
    raw_body: Optional[str] = None         # original text before cleaning
    ingested_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise ValueError(f"unknown source {self.source!r}; expected {SOURCES}")
        self.raw_body = self.raw_body if self.raw_body is not None else self.body
        self.body = clean_text(self.body)
        self.title = clean_text(self.title) or None
        self.author = (self.author or None)
        self.created_at = to_iso(self.created_at)
        if isinstance(self.rating, str) and self.rating.isdigit():
            self.rating = int(self.rating)

    @property
    def content_hash(self) -> str:
        return content_hash(self.source, self.body, self.author)

    @property
    def is_empty(self) -> bool:
        """Edge cases I2/I6 — rating-only or emoji-only entries carry no text."""
        return len(self.body) == 0


class BaseCollector(ABC):
    """A source-specific fetcher. Subclasses yield RawReview instances.

    ``available()`` lets the orchestrator skip a collector cleanly when its
    optional dependency or credentials are missing (graceful degradation),
    rather than crashing the whole run.
    """

    source: str = ""

    def available(self) -> tuple[bool, str]:
        """Return (ok, reason). Override when a dep/credential is required."""
        return True, ""

    @abstractmethod
    def collect(self, limit: int) -> Iterator[RawReview]:
        """Yield up to ``limit`` reviews for this source."""
        raise NotImplementedError
