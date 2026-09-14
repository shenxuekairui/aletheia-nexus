import re
from urllib.parse import urlsplit, urlunsplit

_MARKDOWN_LINK_PATTERN = re.compile(
    r"^\[[^\]]*\]\((https?://.+)\)$",
    re.IGNORECASE,
)


def _unwrap_candidate_url(value: str) -> str:
    """Remove safe whole-value wrappers around a candidate URL."""

    value = value.strip()

    markdown_match = _MARKDOWN_LINK_PATTERN.fullmatch(value)
    if markdown_match:
        value = markdown_match.group(1).strip()

    wrappers = (
        ("<", ">"),
        ('"', '"'),
        ("'", "'"),
    )

    for left, right in wrappers:
        if value.startswith(left) and value.endswith(right):
            value = value[len(left) : -len(right)].strip()
            break

    return value


def normalize_candidate_url(value: str) -> str:
    """Return a clean, absolute HTTP(S) candidate URL.

    Discovery providers are external inputs. Candidate URLs must therefore
    be normalized and validated before they become acquisition inputs.
    URL fragments are removed because they are not sent to the server and
    should not make otherwise identical candidates distinct.
    """

    if not isinstance(value, str):
        raise TypeError("Candidate URL must be a string")

    value = _unwrap_candidate_url(value)

    if not value:
        raise ValueError("Candidate URL must not be empty")

    if any(char.isspace() for char in value):
        raise ValueError("Candidate URL must not contain whitespace")

    try:
        parts = urlsplit(value)
        _ = parts.port
    except ValueError as exc:
        raise ValueError("Candidate URL is malformed") from exc

    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("Candidate URL must use HTTP or HTTPS")

    if parts.hostname is None:
        raise ValueError("Candidate URL must contain a host")

    if parts.username is not None or parts.password is not None:
        raise ValueError("Candidate URL must not contain embedded credentials")

    return urlunsplit(
        (
            scheme,
            parts.netloc.lower(),
            parts.path,
            parts.query,
            "",
        )
    )
