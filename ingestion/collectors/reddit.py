"""Reddit collector — r/spotify and r/truespotify (posts + comments).

Two paths:
  1. Authenticated via PRAW when REDDIT_CLIENT_ID/SECRET are set (preferred —
     higher limits, comments).
  2. Public ``.json`` endpoints via ``requests`` as a no-credentials fallback
     (posts + top-level comments only). Requires only the ``requests`` package.

If neither requests nor praw is importable, the collector is skipped.
"""

from __future__ import annotations

import os
import time
from typing import Iterator

from ..base import BaseCollector, RawReview

SUBREDDITS = ("spotify", "truespotify")
BASE = "https://www.reddit.com"
UA = os.environ.get("REDDIT_USER_AGENT", "spotify-review-analyzer/0.1")


class RedditCollector(BaseCollector):
    source = "reddit"

    def available(self) -> tuple[bool, str]:
        have_praw = _can_import("praw") and os.environ.get("REDDIT_CLIENT_ID")
        have_requests = _can_import("requests")
        if not (have_praw or have_requests):
            return False, "install requests (public mode) or praw + set REDDIT_* creds"
        return True, ""

    def collect(self, limit: int) -> Iterator[RawReview]:
        if _can_import("praw") and os.environ.get("REDDIT_CLIENT_ID"):
            yield from self._collect_praw(limit)
        else:
            yield from self._collect_public(limit)

    # --- authenticated path -------------------------------------------------
    def _collect_praw(self, limit: int) -> Iterator[RawReview]:
        import praw

        reddit = praw.Reddit(
            client_id=os.environ["REDDIT_CLIENT_ID"],
            client_secret=os.environ["REDDIT_CLIENT_SECRET"],
            user_agent=UA,
        )
        per_sub = max(1, limit // len(SUBREDDITS))
        count = 0
        for sub in SUBREDDITS:
            for post in reddit.subreddit(sub).new(limit=per_sub):
                if count >= limit:
                    return
                count += 1
                yield RawReview(
                    source=self.source,
                    source_url=f"{BASE}{post.permalink}",
                    author=str(post.author) if post.author else None,
                    title=post.title,
                    body=post.selftext or post.title or "",
                    created_at=post.created_utc,
                )

    # --- public no-auth fallback (RSS) -------------------------------------
    # Reddit blocks the .json API from datacenter IPs (403) but serves Atom RSS
    # feeds, albeit with aggressive rate limiting (429). We fetch each feed with
    # backoff and space requests out. RSS gives posts only (no comments).
    def _collect_public(self, limit: int) -> Iterator[RawReview]:
        import requests

        browser_ua = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
        count = 0
        for i, sub in enumerate(SUBREDDITS):
            if count >= limit:
                return
            if i > 0:
                time.sleep(8)  # space out to dodge 429 between subreddits
            xml = self._fetch_rss(requests, sub, browser_ua)
            if not xml:
                continue
            for review in self._parse_atom(xml):
                if count >= limit:
                    return
                count += 1
                yield review

    def _fetch_rss(self, requests, sub: str, ua: str):
        url = f"{BASE}/r/{sub}/new/.rss"
        for attempt in range(4):
            try:
                resp = requests.get(url, headers={"User-Agent": ua}, timeout=30)
                if resp.status_code == 429:
                    time.sleep(6 * (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp.content
            except Exception as exc:  # noqa: BLE001 - best-effort
                print(f"  [reddit] r/{sub} attempt {attempt + 1}: {exc}")
                time.sleep(4)
        print(f"  [reddit] r/{sub} skipped (rate-limited)")
        return None

    def _parse_atom(self, xml: bytes) -> Iterator[RawReview]:
        import xml.etree.ElementTree as ET

        ns = {"a": "http://www.w3.org/2005/Atom"}
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            print(f"  [reddit] feed parse error: {exc}")
            return
        for entry in root.findall("a:entry", ns):
            title_el = entry.find("a:title", ns)
            link_el = entry.find("a:link", ns)
            content_el = entry.find("a:content", ns)
            author_el = entry.find("a:author/a:name", ns)
            updated_el = entry.find("a:updated", ns)
            title = title_el.text if title_el is not None else None
            body = title or ""
            if content_el is not None and content_el.text:
                import re

                body = re.sub(r"<[^>]+>", " ", content_el.text)
            yield RawReview(
                source=self.source,
                source_url=link_el.get("href") if link_el is not None else None,
                author=author_el.text if author_el is not None else None,
                title=title,
                body=body,
                created_at=updated_el.text if updated_el is not None else None,
            )


def _can_import(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False
