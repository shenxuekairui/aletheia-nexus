"""File-scoped PLOS corpus redirects; never authorize an entire cloud host."""

import re
from urllib.parse import parse_qs, unquote, urlsplit


def storage_url_allowed(source_url, target_url):
    source, target = urlsplit(source_url), urlsplit(target_url)
    host = (source.hostname or "").lower()
    if not (
        host == "plos.org" or host.endswith(".plos.org")
    ) or not source.path.endswith("/article/file"):
        return False
    query = parse_qs(source.query)
    ids = query.get("id", [])
    if query.get("type") != ["supplementary"] or len(ids) != 1:
        return False
    identifier = ids[0].removeprefix("info:doi/")
    match = re.fullmatch(r"(10\.1371/(?:journal\.)?[^/]+)\.(s\d+)", identifier, re.I)
    if not match:
        return False
    # The actual official /article/file response supplies the account-specific
    # signed redirect. Bind its object to the exact parent and SI identifier.
    if (
        target.scheme != "https"
        or target.username
        or target.password
        or target.port not in {None, 443}
    ):
        return False
    if not re.fullmatch(
        r"corpus-prod\.[a-f0-9]{32}\.r2\.cloudflarestorage\.com",
        target.hostname or "",
        re.I,
    ):
        return False
    from .supplements import _SUFFIXES

    filename = match[1].split("/", 1)[1].removeprefix("journal.") + "." + match[2]
    path = unquote(target.path)
    prefix = re.escape("/" + match[1]) + r"/[1-9]\d*/" + re.escape(filename)
    return any(
        re.fullmatch(prefix + re.escape(suffix), path, re.I) for suffix in _SUFFIXES
    )
