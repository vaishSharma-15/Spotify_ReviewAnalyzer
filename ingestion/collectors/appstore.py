"""Apple App Store collector — Spotify (US storefront).

Uses Apple's public "customer reviews" RSS-as-JSON endpoint, which needs no API
key and no third-party package (standard library only). This makes Phase 1
demonstrably live out of the box.

Endpoint shape:
  https://itunes.apple.com/{country}/rss/customerreviews/page={n}/id={appId}/sortby=mostrecent/json
Apple caps this feed at ~10 pages (≈500 reviews) per storefront.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Iterator

from ..base import BaseCollector, RawReview

SPOTIFY_APP_ID = "324684580"  # Spotify - Music and Podcasts (App Store)
MAX_PAGES = 10                 # Apple's hard limit per storefront for this feed

# Apple caps the feed at ~500 reviews per storefront, so to reach higher volume
# we span several English-language storefronts. Dedup (content_hash) safely
# absorbs any overlap between them.
DEFAULT_COUNTRIES = ("us", "gb", "ca", "au", "ie", "nz", "in", "za", "sg", "ph")


class AppStoreCollector(BaseCollector):
    source = "app_store"

    def __init__(self, app_id: str = SPOTIFY_APP_ID, countries=DEFAULT_COUNTRIES):
        self.app_id = app_id
        # accept a single country string or an iterable of them
        self.countries = (countries,) if isinstance(countries, str) else tuple(countries)

    def _url(self, country: str, page: int) -> str:
        return (
            f"https://itunes.apple.com/{country}/rss/customerreviews/"
            f"page={page}/id={self.app_id}/sortby=mostrecent/json"
        )

    def collect(self, limit: int) -> Iterator[RawReview]:
        yielded = 0
        for country in self.countries:
            if yielded >= limit:
                return
            for page in range(1, MAX_PAGES + 1):
                if yielded >= limit:
                    return
                try:
                    req = urllib.request.Request(
                        self._url(country, page),
                        headers={"User-Agent": "spotify-review-analyzer/0.1"},
                    )
                    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                        payload = json.loads(resp.read().decode("utf-8"))
                except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
                    # Edge case I4 — source error mid-scrape: stop this storefront
                    # cleanly and move to the next. Partial scrape is fine.
                    print(f"  [app_store:{country}] stopped at page {page}: {exc}")
                    break

                entries = payload.get("feed", {}).get("entry", [])
                if not entries:
                    break
                if isinstance(entries, dict):
                    entries = [entries]
                for entry in entries:
                    if "im:rating" not in entry:  # the app-info entry, not a review
                        continue
                    if yielded >= limit:
                        return
                    review = self._parse(entry, country)
                    if review:
                        yielded += 1
                        yield review

    def _parse(self, entry: dict, country: str) -> RawReview | None:
        def g(field: str) -> str | None:
            node = entry.get(field)
            return node.get("label") if isinstance(node, dict) else None

        author = None
        link = None
        if isinstance(entry.get("author"), dict):
            author = entry["author"].get("name", {}).get("label")
            link = entry["author"].get("uri", {}).get("label")

        rating = g("im:rating")
        return RawReview(
            source=self.source,
            source_url=link or f"https://apps.apple.com/{country}/app/id{self.app_id}",
            author=author,
            title=g("title"),
            body=g("content") or "",
            rating=int(rating) if rating and rating.isdigit() else None,
            created_at=g("updated"),
            lang="en",
        )
