from urllib.parse import urljoin, urlsplit, urlunsplit


def _netloc(hostname: str, port: int | None) -> str:
    host = hostname.lower().rstrip(".")
    if ":" in host:
        host = f"[{host}]"
    return host if port is None else f"{host}:{port}"


def normalize_derived_url(value: str, *, base_url: str) -> str | None:
    """Normalize an extracted HTTP(S) URL without inventing a new route.

    This helper is intentionally less opinionated than Discovery URL
    canonicalization: it resolves relative references and removes fragments, but
    it does not silently upgrade HTTP to HTTPS. Explicit protocol upgrades remain
    traceable derivations in the acquisition layer.
    """

    if not isinstance(value, str):
        return None
    raw = value.strip().strip("<>'\"")
    if not raw or raw.startswith("#"):
        return None
    if raw.lower().startswith(("javascript:", "mailto:", "data:", "tel:")):
        return None

    absolute = urljoin(base_url, raw)
    try:
        parts = urlsplit(absolute)
        port = parts.port
    except ValueError:
        return None

    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or not parts.hostname:
        return None
    if parts.username or parts.password:
        return None

    default_port = 80 if scheme == "http" else 443
    normalized_port = None if port in {None, default_port} else port
    return urlunsplit(
        (
            scheme,
            _netloc(parts.hostname, normalized_port),
            parts.path or "/",
            parts.query,
            "",
        )
    )


def derive_https_url(url: str) -> str | None:
    """Return a traceable HTTPS alternative for one absolute HTTP URL."""

    try:
        parts = urlsplit(url)
        port = parts.port
    except (TypeError, ValueError):
        return None

    if parts.scheme.lower() != "http" or not parts.hostname:
        return None
    if parts.username or parts.password:
        return None

    # Port 80 is the HTTP default and should not be carried into an HTTPS
    # alternative. Explicit non-default ports remain part of the route evidence.
    https_port = None if port in {None, 80} else port
    return urlunsplit(
        (
            "https",
            _netloc(parts.hostname, https_port),
            parts.path or "/",
            parts.query,
            "",
        )
    )
