"""Social media conversations collector.

Two paths, chosen automatically:
  1. X/Twitter recent search when TWITTER_BEARER_TOKEN is set (paid API).
  2. Hacker News (Algolia API) as a **no-account, no-key fallback** — public
     developer conversations that frequently discuss Spotify discovery,
     recommendations and playlists. Requires only the ``requests`` package.

This keeps "social media conversations" available out of the box while still
supporting Twitter for anyone who has API access.
"""

from __future__ import annotations

import html
import os
import re
import time
from typing import Iterator

from ..base import BaseCollector, RawReview

# Twitter
SEARCH_QUERY = "(Spotify) (discover OR recommendation OR playlist) lang:en -is:retweet"
TWITTER_RECENT_URL = "https://api.twitter.com/2/tweets/search/recent"

# Hacker News (Algolia). Multiple queries broaden coverage; Algolia caps each
# query near 1000 results, so several terms are needed to reach high volume.
HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
HN_QUERIES = (
    "spotify discovery",
    "spotify recommendation",
    "spotify playlist",
    "spotify algorithm",
    "spotify discover weekly",
    "spotify music",
    "spotify podcast",
    "spotify subscription",
    "spotify wrapped",
    "spotify shuffle",
    "spotify radio",
    "spotify artist",
    "spotify",
)
HN_ITEM_URL = "https://news.ycombinator.com/item?id={id}"
_TAG_RE = re.compile(r"<[^>]+>")


class SocialCollector(BaseCollector):
    source = "social"

    def available(self) -> tuple[bool, str]:
        try:
            import requests  # noqa: F401
        except ImportError:
            return False, "install requests (pip install requests)"
        return True, ""  # HN fallback needs no credentials

    def collect(self, limit: int) -> Iterator[RawReview]:
        if os.environ.get("TWITTER_BEARER_TOKEN"):
            yield from self._collect_twitter(limit)
        else:
            yield from self._collect_hn(limit)

    # --- no-account fallback: Hacker News -----------------------------------
    def _collect_hn(self, limit: int) -> Iterator[RawReview]:
        import requests

        per_query = max(1, limit // len(HN_QUERIES))
        count = 0
        for query in HN_QUERIES:
            if count >= limit:
                return
            page = 0
            fetched_q = 0
            while fetched_q < per_query and count < limit:
                try:
                    resp = requests.get(
                        HN_SEARCH_URL,
                        params={
                            "query": query,
                            "tags": "comment",
                            "hitsPerPage": min(100, per_query - fetched_q),
                            "page": page,
                        },
                        headers={"User-Agent": "spotify-review-analyzer/0.1"},
                        timeout=30,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as exc:  # noqa: BLE001 - best-effort
                    print(f"  [social:hn] query {query!r} stopped: {exc}")
                    break

                hits = data.get("hits", [])
                if not hits:
                    break
                for hit in hits:
                    text = self._clean_hn(hit.get("comment_text"))
                    if not text:
                        continue
                    if count >= limit:
                        return
                    count += 1
                    fetched_q += 1
                    oid = hit.get("objectID")
                    yield RawReview(
                        source=self.source,
                        source_url=HN_ITEM_URL.format(id=oid) if oid else None,
                        author=hit.get("author"),
                        title=hit.get("story_title"),
                        body=text,
                        created_at=hit.get("created_at"),
                        lang="en",
                    )
                page += 1
                if page >= data.get("nbPages", 0):
                    break
                time.sleep(0.3)  # be polite to the API

    @staticmethod
    def _clean_hn(comment_html: str | None) -> str:
        if not comment_html:
            return ""
        text = _TAG_RE.sub(" ", comment_html)
        return html.unescape(text)

    # --- authenticated path: X/Twitter --------------------------------------
    def _collect_twitter(self, limit: int) -> Iterator[RawReview]:
        import requests

        headers = {"Authorization": f"Bearer {os.environ['TWITTER_BEARER_TOKEN']}"}
        next_token = None
        fetched = 0
        while fetched < limit:
            params = {
                "query": SEARCH_QUERY,
                "max_results": min(100, max(10, limit - fetched)),
                "tweet.fields": "created_at,author_id,lang",
            }
            if next_token:
                params["next_token"] = next_token
            try:
                resp = requests.get(
                    TWITTER_RECENT_URL, headers=headers, params=params, timeout=30
                )
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:  # noqa: BLE001 - best-effort
                print(f"  [social:twitter] stopped: {exc}")
                return

            for tw in payload.get("data", []):
                if fetched >= limit:
                    return
                fetched += 1
                tid = tw.get("id")
                yield RawReview(
                    source=self.source,
                    source_url=f"https://twitter.com/i/web/status/{tid}" if tid else None,
                    author=tw.get("author_id"),
                    title=None,
                    body=tw.get("text") or "",
                    created_at=tw.get("created_at"),
                    lang=tw.get("lang"),
                )
            next_token = payload.get("meta", {}).get("next_token")
            if not next_token:
                return
