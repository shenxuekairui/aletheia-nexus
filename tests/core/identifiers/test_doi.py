import pytest

from aletheia_nexus.core.identifiers.doi import (
    extract_dois,
    looks_like_doi,
    normalize_doi,
    normalize_dois,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "10.1021/ACS.JOC.5C01234",
            "10.1021/acs.joc.5c01234",
        ),
        (
            "  10.1021/ACS.JOC.5C01234  ",
            "10.1021/acs.joc.5c01234",
        ),
        (
            "https://doi.org/10.1021/ACS.JOC.5C01234",
            "10.1021/acs.joc.5c01234",
        ),
        (
            "http://dx.doi.org/10.1021/ACS.JOC.5C01234",
            "10.1021/acs.joc.5c01234",
        ),
        (
            "doi.org/10.1021/ACS.JOC.5C01234",
            "10.1021/acs.joc.5c01234",
        ),
        (
            "DOI: 10.1021/ACS.JOC.5C01234",
            "10.1021/acs.joc.5c01234",
        ),
        (
            "https://doi.org/10.1002%2Fanie.202512345",
            "10.1002/anie.202512345",
        ),
        (
            '"10.1021/ACS.JOC.5C01234"',
            "10.1021/acs.joc.5c01234",
        ),
        (
            "10.1021/ACS.JOC.5C01234.",
            "10.1021/acs.joc.5c01234",
        ),
        (
            "10.1002/(SICI)1097-4571(1990)41:1<45::AID-ASI5>3.0.CO;2-7",
            "10.1002/(sici)1097-4571(1990)41:1<45::aid-asi5>3.0.co;2-7",
        ),
    ],
)
def test_normalize_doi(raw, expected):
    assert normalize_doi(raw) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "hello world",
        "https://example.com/article",
        "12345",
    ],
)
def test_invalid_doi(value):
    with pytest.raises(ValueError):
        normalize_doi(value)


def test_non_string_doi():
    with pytest.raises(TypeError):
        normalize_doi(123)


def test_normalize_multiple_dois():
    result = normalize_dois(
        [
            "10.1021/ABC",
            "https://doi.org/10.1002/DEF",
            "doi:10.1021/abc",
        ]
    )

    assert result == [
        "10.1021/abc",
        "10.1002/def",
    ]


def test_normalize_multiple_dois_without_deduplication():
    result = normalize_dois(
        [
            "10.1021/ABC",
            "10.1021/abc",
        ],
        deduplicate=False,
    )

    assert result == [
        "10.1021/abc",
        "10.1021/abc",
    ]


def test_normalize_dois_rejects_single_string():
    with pytest.raises(TypeError):
        normalize_dois("10.1021/abc")


def test_extract_multiple_dois():
    text = """
    The first paper is https://doi.org/10.1021/ABC.
    Another article has DOI 10.1002/DEF,
    and the first one appears again as 10.1021/abc.
    """

    assert extract_dois(text) == [
        "10.1021/abc",
        "10.1002/def",
    ]


def test_extract_dois_without_matches():
    assert extract_dois("There is no DOI here.") == []


def test_looks_like_doi():
    assert looks_like_doi("10.1021/abc") is True
    assert looks_like_doi("not a DOI") is False
