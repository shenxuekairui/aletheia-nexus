from aletheia_nexus.acquire.fulltext.urls import derive_https_url, normalize_derived_url


def test_normalize_derived_url_resolves_relative_and_removes_fragment():
    result = normalize_derived_url(
        "../files/paper.pdf?download=1#page=2",
        base_url="https://Example.org/articles/123/",
    )

    assert result == "https://example.org/articles/files/paper.pdf?download=1"


def test_normalize_derived_url_removes_default_port():
    assert (
        normalize_derived_url(
            "https://Example.org:443/paper.pdf",
            base_url="https://example.org/",
        )
        == "https://example.org/paper.pdf"
    )


def test_normalize_derived_url_rejects_embedded_credentials():
    assert (
        normalize_derived_url(
            "https://user:secret@example.org/paper.pdf",
            base_url="https://example.org/",
        )
        is None
    )


def test_derive_https_url_drops_http_default_port_and_fragment():
    assert (
        derive_https_url("http://Example.org:80/article?x=1#section")
        == "https://example.org/article?x=1"
    )


def test_derive_https_url_preserves_explicit_non_default_port():
    assert (
        derive_https_url("http://example.org:8080/article")
        == "https://example.org:8080/article"
    )
