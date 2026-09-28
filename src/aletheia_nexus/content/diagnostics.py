"""Portable diagnostics safe to persist in parsed artifacts."""

from __future__ import annotations

import re

_URL = re.compile(r"(?i)\bhttps?://\S+")
_WINDOWS_PATH = re.compile(r"(?i)(?<!\w)[a-z]:[\\/][^\s,;]+")
_POSIX_PRIVATE_PATH = re.compile(
    r"(?<!\w)/(?:home|tmp|private/tmp|users|var/folders)/[^\s,;]+",
    re.IGNORECASE,
)


def safe_exception_detail(exc: BaseException, *, limit: int = 300) -> str:
    """Describe a failure without persisting local paths or credentialed URLs."""

    detail = " ".join(str(exc).split()) or "no diagnostic detail"
    detail = _URL.sub("<redacted-url>", detail)
    detail = _WINDOWS_PATH.sub("<redacted-local-path>", detail)
    detail = _POSIX_PRIVATE_PATH.sub("<redacted-local-path>", detail)
    return detail[:limit]
