import pytest

from aletheia_nexus.acquire.discovery.urls import normalize_candidate_url


def test_normalize_candidate_url_unwraps_markdown_link():
    value = "[https://doi.org/10.1038/nphys1170](https://doi.org/10.1038/nphys1170)"

    assert normalize_candidate_url(value) == "https://doi.org/10.1038/nphys1170"


def test_normalize_candidate_url_removes_fragment_and_normalizes_host():
    value = "HTTPS://Example.ORG/paper.pdf#page=2"

    assert normalize_candidate_url(value) == "https://example.org/paper.pdf"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "http://hdl.handle.net/21.11116/0000-0001-B9B9-E",
            "https://hdl.handle.net/21.11116/0000-0001-B9B9-E",
        ),
        (
            "https://dx.doi.org/10.1000/Example",
            "https://doi.org/10.1000/Example",
        ),
        (
            "http://www.doi.org/10.1000/Example",
            "https://doi.org/10.1000/Example",
        ),
    ],
)
def test_normalize_candidate_url_canonicalizes_known_resolvers(value, expected):
    assert normalize_candidate_url(value) == expected


def test_normalize_candidate_url_does_not_force_https_for_ordinary_hosts():
    value = "http://example.org/paper.pdf"

    assert normalize_candidate_url(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "example.org/paper.pdf",
        "ftp://example.org/paper.pdf",
        "https://",
        "https://user:secret@example.org/paper.pdf",
        "https://example.org/a paper.pdf",
    ],
)
def test_normalize_candidate_url_rejects_unsafe_or_incomplete_values(value):
    with pytest.raises(ValueError):
        normalize_candidate_url(value)
