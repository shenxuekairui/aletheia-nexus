import pytest

from aletheia_nexus.core.identifiers.doi import normalize_doi


def test_plain_doi():
    assert normalize_doi("10.1021/acs.joc.5c01234") == "10.1021/acs.joc.5c01234"


def test_doi_url():
    assert (
        normalize_doi("https://doi.org/10.1021/ACS.JOC.5C01234")
        == "10.1021/acs.joc.5c01234"
    )


def test_doi_prefix():
    assert (
        normalize_doi("DOI: 10.1021/acs.joc.5c01234")
        == "10.1021/acs.joc.5c01234"
    )


def test_invalid_doi():
    with pytest.raises(ValueError):
        normalize_doi("this is not a doi")
