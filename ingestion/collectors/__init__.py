"""Source-specific collectors. Each maps to one entry in base.SOURCES."""

from .appstore import AppStoreCollector
from .community import CommunityForumCollector
from .playstore import PlayStoreCollector
from .reddit import RedditCollector
from .social import SocialCollector

# Registry keyed by the CLI --source name (== base.SOURCES values).
COLLECTORS = {
    "app_store": AppStoreCollector,
    "play_store": PlayStoreCollector,
    "reddit": RedditCollector,
    "community_forum": CommunityForumCollector,
    "social": SocialCollector,
}

__all__ = ["COLLECTORS"]
