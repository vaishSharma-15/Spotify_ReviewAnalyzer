"""Google Play Store collector — Spotify.

Wraps the optional ``google-play-scraper`` package. If it isn't installed, the
collector reports itself unavailable and the orchestrator skips it cleanly.
"""

from __future__ import annotations

from typing import Iterator

from ..base import BaseCollector, RawReview

SPOTIFY_PACKAGE = "com.spotify.music"


class PlayStoreCollector(BaseCollector):
    source = "play_store"

    def __init__(self, app_id: str = SPOTIFY_PACKAGE, lang: str = "en", country: str = "us"):
        self.app_id = app_id
        self.lang = lang
        self.country = country

    def available(self) -> tuple[bool, str]:
        try:
            import google_play_scraper  # noqa: F401
        except ImportError:
            return False, "install google-play-scraper (pip install google-play-scraper)"
        return True, ""

    def collect(self, limit: int) -> Iterator[RawReview]:
        from google_play_scraper import Sort, reviews

        fetched = 0
        token = None
        while fetched < limit:
            batch, token = reviews(
                self.app_id,
                lang=self.lang,
                country=self.country,
                sort=Sort.NEWEST,
                count=min(200, limit - fetched),
                continuation_token=token,
            )
            if not batch:
                return
            for item in batch:
                fetched += 1
                yield RawReview(
                    source=self.source,
                    source_url=(
                        f"https://play.google.com/store/apps/details?id={self.app_id}"
                        f"&reviewId={item.get('reviewId')}"
                    ),
                    author=item.get("userName"),
                    title=None,
                    body=item.get("content") or "",
                    rating=item.get("score"),
                    created_at=item.get("at"),  # datetime -> normalized in RawReview
                    lang=self.lang,
                )
            if token is None:
                return
