"""A bibliographic acquisition request; DOI is optional, never synthesized."""

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass

from aletheia_nexus.core.identifiers.doi import normalize_doi


def compact_bibliography(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum()
    )


def bibliographic_field_key(field: str, value: object) -> str:
    compact = compact_bibliography(str(value))
    if field in {"volume", "issue"} and compact.isdigit():
        return str(int(compact))
    return compact


@dataclass(frozen=True, slots=True)
class PaperRequest:
    doi: str | None = None
    title: str | None = None
    authors: tuple[str, ...] = ()
    journal: str | None = None
    year: int | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    cnki_id: str | None = None

    def __post_init__(self):
        if self.doi is not None:
            object.__setattr__(self, "doi", normalize_doi(self.doi))
        for field in ("title", "journal", "volume", "issue", "pages"):
            value = getattr(self, field)
            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{field} must be a non-empty string")
                object.__setattr__(self, field, value.strip())
        if not self.doi and not self.title:
            raise ValueError("A DOI or a title is required")
        if not isinstance(self.authors, tuple) or any(
            not isinstance(a, str) or not a.strip() for a in self.authors
        ):
            raise ValueError("authors must be a tuple of non-empty strings")
        object.__setattr__(self, "authors", tuple(a.strip() for a in self.authors))
        if self.year is not None and (
            type(self.year) is not int or not 1000 <= self.year <= 9999
        ):
            raise ValueError("year must be a four-digit integer")
        if self.cnki_id is not None:
            if not isinstance(self.cnki_id, str) or not re.fullmatch(
                r"cnki:[A-Za-z0-9_]+:[A-Za-z0-9_.-]+", self.cnki_id
            ):
                raise ValueError("cnki_id must be cnki:<database>:<filename>")
            object.__setattr__(self, "cnki_id", self.cnki_id.casefold())

    @property
    def key(self) -> str:
        """Includes all constraints so a changed request cannot resume old evidence."""
        payload = asdict(self)
        for key, value in payload.items():
            if isinstance(value, str) and key not in {"doi", "cnki_id"}:
                payload[key] = compact_bibliography(value)
        payload["authors"] = sorted(compact_bibliography(a) for a in self.authors)
        return (
            "citation:"
            + hashlib.sha256(
                json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
        )

    @property
    def article_id(self) -> str:
        return (
            "doi:" + self.doi
            if self.doi
            else self.cnki_id or "bibliographic:" + self.key.split(":", 1)[1]
        )
