"""Spotify Community forum collector (community.spotify.com).

The forum runs on Khoros. Its legacy RSS now returns an HTML shell (no items),
so we scrape the HTML directly: list topic links from each board page, then
fetch each topic and extract the opening post body. A browser-like User-Agent is
required (bot UAs get 403). Requires ``requests``; skipped if it's missing.
"""

from __future__ import annotations

import html
import re
import time
from typing import Iterator

from ..base import BaseCollector, RawReview, clean_text

BASE = "https://community.spotify.com"

# Discovery-relevant boards (IDs verified 2026-06).
BOARDS = (
    "/t5/Music-Discussion/bd-p/music_discussion",
    "/t5/Discovery-Promo/bd-p/discovery_and_promo",
    "/t5/Your-Library/bd-p/yourlibrary",
    "/t5/Live-Ideas/idb-p/ideas_live",
    "/t5/Music-Exchange/bd-p/music_exchange",
    "/t5/Podcast-Discussion/bd-p/podcast_discussion",
    "/t5/Android/bd-p/spotifyandroid",
    "/t5/iOS-iPhone-iPad/bd-p/spotifyiOS",
)

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

_TOPIC_RE = re.compile(r'href="(/t5/[^"]*?/(?:m-p|td-p)/\d+)"[^>]*>(.*?)</a>', re.S)
_BODY_RE = re.compile(r'class="lia-message-body-content">(.*?)</div>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_PAGE_PARAM = "/page/{n}"


class CommunityForumCollector(BaseCollector):
    source = "community_forum"

    def available(self) -> tuple[bool, str]:
        try:
            import requests  # noqa: F401
        except ImportError:
            return False, "install requests (pip install requests)"
        return True, ""

    def collect(self, limit: int) -> Iterator[RawReview]:
        import requests

        session = requests.Session()
        session.headers.update({"User-Agent": _BROWSER_UA})
        count = 0
        seen: set[str] = set()

        for board in BOARDS:
            if count >= limit:
                return
            page = 1
            empty_pages = 0
            while count < limit and empty_pages < 1:
                board_url = f"{BASE}{board}" + (f"/page/{page}" if page > 1 else "")
                try:
                    resp = session.get(board_url, timeout=30)
                    resp.raise_for_status()
                except Exception as exc:  # noqa: BLE001 - best-effort per board
                    print(f"  [community_forum] board skipped: {exc}")
                    break

                topics = self._topic_links(resp.text, seen)
                if not topics:
                    empty_pages += 1
                    break
                for href, title in topics:
                    if count >= limit:
                        return
                    review = self._fetch_topic(session, href, title)
                    if review:
                        count += 1
                        yield review
                    time.sleep(0.4)  # be polite
                page += 1

    def _topic_links(self, page_html: str, seen: set[str]) -> list[tuple[str, str]]:
        out = []
        for href, raw_title in _TOPIC_RE.findall(page_html):
            if href in seen:
                continue
            title = clean_text(html.unescape(_TAG_RE.sub("", raw_title)))
            # skip pinned guideline/blog index noise
            if not title or title.lower().startswith(("[guidelines]", "[guideline]")):
                continue
            seen.add(href)
            out.append((href, title))
        return out

    def _fetch_topic(self, session, href: str, title: str):
        url = BASE + href
        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
        except Exception:  # noqa: BLE001 - skip a single bad topic
            return None
        m = _BODY_RE.search(resp.text)
        body = ""
        if m:
            body = clean_text(html.unescape(_TAG_RE.sub(" ", m.group(1))))
        author = None
        am = re.search(r'class="lia-user-name-link"[^>]*>(?:<span[^>]*>)?([^<]+)', resp.text)
        if am:
            author = am.group(1).strip()
        return RawReview(
            source=self.source,
            source_url=url,
            author=author,
            title=title,
            body=body or title,
            lang="en",
        )
