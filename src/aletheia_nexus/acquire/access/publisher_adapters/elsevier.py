"""Resolve Elsevier's observed LinkingHub PII to its official article page."""

import re
from urllib.parse import SplitResult

from .base import PublisherAdapter


class LinkingHubAdapter(PublisherAdapter):
    name = "elsevier-linkinghub"

    def matches(self, doi: str | None, parts: SplitResult) -> bool:
        return (parts.hostname or "").casefold() == "linkinghub.elsevier.com"

    def article_route(self, parts: SplitResult) -> str | None:
        match = re.fullmatch(r"/retrieve/pii/(S[0-9]{16})/?", parts.path)
        if match:
            return f"https://www.sciencedirect.com/science/article/pii/{match.group(1)}"
        return None
