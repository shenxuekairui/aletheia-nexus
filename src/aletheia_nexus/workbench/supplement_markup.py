"""Publisher-independent, bounded supplementary link semantics; no script execution."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser

from aletheia_nexus.acquire.fulltext.resolution.parser import HtmlLink
from aletheia_nexus.core.identifiers.doi import extract_dois

LIMIT = 256
MAX_LINKS = 4096
_VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_BOUNDARY = re.compile(
    r"^(?:references|bibliography|acknowledg?ments?|author information|article information|permissions|参考文献)\b",
    re.I,
)


class SupplementMarkup(HTMLParser):
    """Keep semantic containers and headings scoped to actual link occurrences."""

    def __init__(self, role):
        super().__init__(convert_charrefs=True)
        self.role = role
        self.stack, self.headings, self.links = [], {}, []
        self.heading, self.heading_text = None, []
        self.active = []
        self.truncated = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        hidden = tag in {"script", "style", "template", "nav", "footer"} or any(
            node[2] for node in self.stack
        )
        semantic = " ".join(
            values.get(key) or "" for key in ("id", "class", "aria-label", "data-title")
        )
        role = (
            self.role(semantic)
            if tag in {"section", "div", "aside", "li", "article"}
            else None
        )
        if tag not in _VOID:
            self.stack.append((tag, role, hidden))
        if hidden:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self.heading, self.heading_text = int(tag[1]), []
        href = (
            values.get("href")
            if tag in {"a", "link"}
            else values.get("data-href")
            if tag == "button"
            else None
        )
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            return
        if len(self.links) >= MAX_LINKS:
            self.truncated = True
            return
        headings = [
            value for _, value in sorted(self.headings.items()) if value is not None
        ]
        section = headings[-1] if headings else None
        container = next((node[1] for node in reversed(self.stack) if node[1]), None)
        if section is False:
            container = None
        label = " ".join(
            values.get(key) or "" for key in ("title", "aria-label", "download")
        )
        entry = {
            "tag": tag,
            "url": href,
            "text": [],
            "label": label,
            "type": values.get("type"),
            "rel": tuple((values.get("rel") or "").lower().split()),
            "role": container or section or None,
        }
        self.links.append(entry)
        if tag == "a":
            self.active.append(len(self.links) - 1)

    def handle_data(self, data):
        if any(node[2] for node in self.stack):
            return
        if self.heading is not None:
            self.heading_text.append(data)
        if self.active:
            self.links[self.active[-1]]["text"].append(data)

    def handle_endtag(self, tag):
        if self.heading is not None and tag == f"h{self.heading}":
            label = " ".join(self.heading_text).strip()
            self.headings = {
                level: role
                for level, role in self.headings.items()
                if level < self.heading
            }
            self.headings[self.heading] = (
                False if _BOUNDARY.match(label) else self.role(label)
            )
            self.heading, self.heading_text = None, []
        if tag == "a" and self.active:
            self.active.pop()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def candidates(self):
        return [
            (
                HtmlLink(
                    tag=e["tag"],
                    url=e["url"],
                    text=" ".join(e["text"]),
                    type_attr=e["type"],
                    title_attr=e["label"],
                    rel=e["rel"],
                ),
                e["role"],
            )
            for e in self.links
        ]


def structured_articles(parsed):
    """Only top-level/@graph articles; cited works do not establish page identity."""
    articles = []
    for payload in parsed.json_ld[:20]:
        try:
            value = json.loads(payload)
        except (ValueError, TypeError, RecursionError):
            continue
        roots = value if isinstance(value, list) else [value]
        nodes = roots[:100]
        for node in roots[:100]:
            if isinstance(node, dict) and isinstance(node.get("@graph"), list):
                nodes = [*nodes, *node["@graph"][:100]]
        for node in nodes[:200]:
            if not isinstance(node, dict):
                continue
            types = node.get("@type", [])
            types = [types] if isinstance(types, str) else types
            if isinstance(types, list) and set(
                t for t in types if isinstance(t, str)
            ) & {"Article", "ScholarlyArticle", "MedicalScholarlyArticle"}:
                ids = node.get("identifier")
                identifiers = [
                    node.get("@id"),
                    node.get("doi"),
                    *(ids[:20] if isinstance(ids, list) else [ids]),
                ]
                dois = set()
                for identifier in identifiers:
                    if isinstance(identifier, dict):
                        identifier = identifier.get("value")
                    if isinstance(identifier, str):
                        dois.update(extract_dois(identifier))
                if dois:
                    articles.append((node, dois))
    return articles


def structured_links(articles, doi, role):
    candidates = []
    for node, identifiers in articles:
        if identifiers != {doi}:
            continue
        for field in ("associatedMedia", "hasPart", "supplementaryMaterial"):
            media = node.get(field, [])
            for entry in (media if isinstance(media, list) else [media])[:LIMIT]:
                if not isinstance(entry, dict):
                    continue
                label = " ".join(
                    entry.get(key, "")
                    for key in ("name", "description")
                    if isinstance(entry.get(key), str)
                )
                purpose = role(label) or (
                    "SUPPLEMENT" if field == "supplementaryMaterial" else None
                )
                url = entry.get("contentUrl")
                if purpose and isinstance(url, str):
                    candidates.append(
                        (
                            HtmlLink(
                                tag="jsonld",
                                url=url,
                                text=label,
                                type_attr=entry.get("encodingFormat")
                                if isinstance(entry.get("encodingFormat"), str)
                                else None,
                            ),
                            purpose,
                        )
                    )
                if len(candidates) >= LIMIT:
                    return candidates, True
    return candidates, False
