from dataclasses import dataclass
from html.parser import HTMLParser
from re import IGNORECASE
from re import compile as re_compile
from re import sub as re_sub

_SCRIPT_PDF_URL = re_compile(
    r"""(?P<quote>["'])(?P<url>(?:(?:https?:)?//|/|\./|\.\./)?[^"'<>\\\s]*?\.pdf(?:\?[^"'<>\\\s]*)?)(?P=quote)""",
    IGNORECASE,
)


def _extract_script_pdf_urls(value: str) -> tuple[str, ...]:
    """Extract only explicit quoted PDF URL/path values from inline script text."""

    normalized = value.replace("\\/", "/")
    normalized = re_sub(r"\\u002[fF]", "/", normalized)
    normalized = re_sub(r"\\u003[aA]", ":", normalized)
    normalized = re_sub(r"\\u0026", "&", normalized, flags=IGNORECASE)

    found: list[str] = []
    for match in _SCRIPT_PDF_URL.finditer(normalized):
        url = match.group("url").strip()
        if url and url not in found:
            found.append(url)
    return tuple(found)


@dataclass(frozen=True, slots=True)
class HtmlLink:
    tag: str
    url: str
    text: str = ""
    type_attr: str | None = None
    rel: tuple[str, ...] = ()
    title_attr: str | None = None
    download: bool = False


@dataclass(frozen=True, slots=True)
class ParsedHtml:
    title: str | None
    base_href: str | None
    metadata: tuple[tuple[str, str], ...]
    links: tuple[HtmlLink, ...]
    json_ld: tuple[str, ...]
    visible_text: str

    def metadata_values(self, *names: str) -> tuple[str, ...]:
        wanted = {name.lower() for name in names}
        return tuple(value for key, value in self.metadata if key in wanted)


class _ScholarlyHtmlParser(HTMLParser):
    _NON_VISIBLE_TEXT_TAGS = {"script", "style", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.metadata: list[tuple[str, str]] = []
        self.links: list[dict[str, object]] = []
        self.anchor_stack: list[int] = []
        self.title_parts: list[str] = []
        self.in_title = False
        self.base_href: str | None = None
        self.json_ld: list[str] = []
        self.in_json_ld = False
        self.json_parts: list[str] = []
        self.in_script = False
        self.visible_parts: list[str] = []
        self.non_visible_text_depth = 0

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {key.lower(): value or "" for key, value in attrs}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = self._attrs(attrs)

        if tag == "title":
            self.in_title = True

        if tag in self._NON_VISIBLE_TEXT_TAGS:
            self.non_visible_text_depth += 1

        if tag == "script":
            self.in_script = True

        if tag == "base" and not self.base_href:
            href = values.get("href", "").strip()
            if href:
                self.base_href = href

        if tag == "meta":
            content = values.get("content", "").strip()
            key = (
                (
                    values.get("name")
                    or values.get("property")
                    or values.get("itemprop")
                    or values.get("http-equiv")
                    or ""
                )
                .strip()
                .lower()
            )
            if key and content:
                self.metadata.append((key, content))

        if tag == "script" and values.get("type", "").lower() == "application/ld+json":
            self.in_json_ld = True
            self.json_parts = []

        url_attr = None
        if tag in {"a", "link"}:
            url_attr = "href"
        elif tag in {"iframe", "embed"}:
            url_attr = "src"
        elif tag == "object":
            url_attr = "data"

        if url_attr:
            url = values.get(url_attr, "").strip()
            if url:
                rel = tuple(
                    token.lower()
                    for token in values.get("rel", "").replace(",", " ").split()
                    if token
                )
                self.links.append(
                    {
                        "tag": tag,
                        "url": url,
                        "text_parts": [],
                        "type_attr": values.get("type") or None,
                        "rel": rel,
                        "title_attr": values.get("title") or None,
                        "download": "download" in values,
                    }
                )
                if tag == "a":
                    self.anchor_stack.append(len(self.links) - 1)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self.in_title = False
        if tag == "a" and self.anchor_stack:
            self.anchor_stack.pop()
        if tag == "script" and self.in_json_ld:
            payload = "".join(self.json_parts).strip()
            if payload:
                self.json_ld.append(payload)
            self.in_json_ld = False
            self.json_parts = []
        if tag == "script":
            self.in_script = False
        if tag in self._NON_VISIBLE_TEXT_TAGS and self.non_visible_text_depth:
            self.non_visible_text_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if self.in_json_ld:
            self.json_parts.append(data)
            return
        if self.in_script:
            for url in _extract_script_pdf_urls(data):
                self.links.append(
                    {
                        "tag": "script",
                        "url": url,
                        "text_parts": [],
                        "type_attr": None,
                        "rel": (),
                        "title_attr": None,
                        "download": False,
                    }
                )
            return
        if self.non_visible_text_depth:
            return
        text = data.strip()
        if text:
            self.visible_parts.append(text)
            if self.anchor_stack:
                index = self.anchor_stack[-1]
                parts = self.links[index]["text_parts"]
                assert isinstance(parts, list)
                parts.append(text)


def parse_html(text: str) -> ParsedHtml:
    """Parse generic scholarly HTML without publisher-specific assumptions."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    parser = _ScholarlyHtmlParser()
    parser.feed(text)
    parser.close()

    links: list[HtmlLink] = []
    for item in parser.links:
        text_parts = item["text_parts"]
        assert isinstance(text_parts, list)
        links.append(
            HtmlLink(
                tag=str(item["tag"]),
                url=str(item["url"]),
                text=" ".join(str(part) for part in text_parts).strip(),
                type_attr=(
                    str(item["type_attr"]) if item["type_attr"] is not None else None
                ),
                rel=tuple(str(value) for value in item["rel"]),
                title_attr=(
                    str(item["title_attr"]) if item["title_attr"] is not None else None
                ),
                download=bool(item["download"]),
            )
        )

    page_title = " ".join(" ".join(parser.title_parts).split()) or None
    visible_text = " ".join(parser.visible_parts)

    return ParsedHtml(
        title=page_title,
        base_href=parser.base_href,
        metadata=tuple(parser.metadata),
        links=tuple(links),
        json_ld=tuple(parser.json_ld),
        visible_text=visible_text,
    )
