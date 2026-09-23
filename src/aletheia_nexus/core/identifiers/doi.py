import re
from collections.abc import Iterable
from urllib.parse import unquote, urlsplit

DOI_PREFIX = r"10\.\d{4,9}"

DOI_PATTERN = re.compile(
    rf"{DOI_PREFIX}/[-._;()/:<>#?A-Z0-9]+",
    re.IGNORECASE,
)

DOI_URL_PATTERN = re.compile(
    r"^(?:https?://)?(?:dx\.)?doi\.org/",
    re.IGNORECASE,
)

DOI_LABEL_PATTERN = re.compile(
    r"^doi\s*[:：]\s*",
    re.IGNORECASE,
)

EXTRACT_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9_/])(?:"
    rf"(?:https?://)?(?:dx\.)?doi\.org/\S+"
    rf"|"
    rf"{DOI_PREFIX}/[-._;()/:<>#?A-Z0-9]+"
    rf")",
    re.IGNORECASE,
)


WRAPPERS = (
    ('"', '"'),
    ("'", "'"),
    ("[", "]"),
    ("(", ")"),
    ("{", "}"),
    ("（", "）"),
    ("【", "】"),
    ("“", "”"),
    ("‘", "’"),
    ("《", "》"),
)

TRAILING_PUNCTUATION = ".,;，。；"

# 中文正文中这些字符用于分隔 DOI 和后续文字。
CJK_BOUNDARIES = str.maketrans(
    {char: " " for char in "，。；、！？（）【】《》“”‘’：…"}
)


def _clean(value: str) -> str:
    """Remove common wrappers and surrounding prose punctuation."""

    value = value.strip()

    while value:
        old = value

        value = value.rstrip(TRAILING_PUNCTUATION).strip()

        for left, right in WRAPPERS:
            if value.startswith(left) and value.endswith(right):
                value = value[len(left) : -len(right)].strip()
                break

        # Remove only unmatched closing ASCII wrappers.
        for left, right in (("(", ")"), ("[", "]"), ("{", "}")):
            if value.endswith(right) and value.count(right) > value.count(left):
                value = value[:-1].rstrip()

        if value == old:
            break

    return value


def _from_doi_url(value: str) -> str:
    """Extract DOI from a doi.org resolver URL."""

    if not re.match(r"^https?://", value, re.IGNORECASE):
        value = "https://" + value

    parsed = urlsplit(value)

    if (parsed.hostname or "").lower() not in {"doi.org", "dx.doi.org"}:
        raise ValueError(f"Invalid DOI URL: {value}")

    return unquote(parsed.path.lstrip("/"))


def looks_like_doi(value: object) -> bool:
    """Return True only for an already-clean bare DOI."""

    if not isinstance(value, str):
        return False

    if value != value.strip():
        return False

    if any(char.isspace() for char in value):
        return False

    if value.endswith(tuple(TRAILING_PUNCTUATION)):
        return False

    return DOI_PATTERN.fullmatch(value) is not None


def normalize_doi(value: str) -> str:
    """Normalize one DOI, DOI label, or doi.org URL."""

    if not isinstance(value, str):
        raise TypeError("DOI must be a string")

    value = _clean(value)
    value = DOI_LABEL_PATTERN.sub("", value, count=1)
    value = _clean(value)

    if DOI_URL_PATTERN.match(value):
        value = _from_doi_url(value)
        value = _clean(value)

    if not looks_like_doi(value):
        raise ValueError(f"Invalid DOI syntax: {value}")

    return value.lower()


def normalize_dois(
    values: Iterable[str],
    *,
    deduplicate: bool = True,
) -> list[str]:
    """Normalize multiple DOIs while preserving order."""

    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise TypeError("normalize_dois() expects an iterable of DOI strings")

    result = [normalize_doi(value) for value in values]

    if deduplicate:
        result = list(dict.fromkeys(result))

    return result


def extract_dois(
    text: str,
    *,
    deduplicate: bool = True,
) -> list[str]:
    """Extract normalized DOIs from natural-language text."""

    if not isinstance(text, str):
        raise TypeError("Text must be a string")

    # 中文文本通常没有空格。
    # 先把中文正文边界转换为空格，再使用统一提取规则。
    searchable = text.translate(CJK_BOUNDARIES)

    result = []

    for match in EXTRACT_PATTERN.finditer(searchable):
        try:
            result.append(normalize_doi(match.group(0)))
        except ValueError:
            continue

    if deduplicate:
        result = list(dict.fromkeys(result))

    return result
