import pytest

from aletheia_nexus.acquire.discovery.urls import normalize_candidate_url


def test_normalize_candidate_url_unwraps_markdown_link():
    value = "[https://doi.org/10.1038/nphys1170](https://doi.org/10.1038/nphys1170)"

    assert normalize_candidate_url(value) == "https://doi.org/10.1038/nphys1170"


def test_normalize_candidate_url_removes_fragment_and_normalizes_host():
    value = "HTTPS://Example.ORG/paper.pdf#page=2"

    assert normalize_candidate_url(value) == "https://example.org/paper.pdf"


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
