import pytest

from aletheia_nexus.core.identifiers.doi import (
    extract_dois,
    extract_pdf_dois,
    looks_like_doi,
    normalize_doi,
    normalize_dois,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            "doi\n:\n10\n.\n16846\n/j.issn.\n1004\n-\n3101\n.\n2025\n.\n03\n.\n003\nST",
            "10.16846/j.issn.1004-3101.2025.03.003",
        ),
        (
            "DOI: 10.19343/j.cnki.11 –1302/c.2025.07.009",
            "10.19343/j.cnki.11-1302/c.2025.07.009",
        ),
        (
            "10. 16112 / j. cnki. 53 － 1160 / c. 2025. 05. 211",
            "10.16112/j.cnki.53-1160/c.2025.05.211",
        ),
        (
            "ＤＯＩ：１０． １３４６２ ／ ｊ． ｃｎｋｉ． ｍｍｔａｍｔ． ２０２５． １０． ００２",
            "10.13462/j.cnki.mmtamt.2025.10.002",
        ),
        (
            "ＤＯＩ：１０． １６１５２ ／ ｊ． ｃｎｋｉ． ｘｄｘｂｚｒ． ２０２５-０３-００２",
            "10.16152/j.cnki.xdxbzr.2025-03-002",
        ),
        (
            "DOI: 10. 13637 / j. issn. 1009-6094. 2025. 0192",
            "10.13637/j.issn.1009-6094.2025.0192",
        ),
    ],
)
def test_cnki_real_pdf_typography(raw, expected):
    assert extract_pdf_dois(raw) == [expected]


def test_sentence_terminal_period_does_not_join_next_word():
    assert extract_pdf_dois("DOI: 10.1000/target.\nAbstract text") == ["10.1000/target"]
    assert extract_pdf_dois("10.1000/target.\n10.2000/other") == [
        "10.1000/target",
        "10.2000/other",
    ]


def test_pdf_doi_fullwidth_and_punctuation_spacing():
    assert extract_pdf_dois("DOI: １０．１３８２２ / j．cnki．hxsj．2023．0002") == [
        "10.13822/j.cnki.hxsj.2023.0002"
    ]
    assert extract_pdf_dois("DOI: 10.13822 / j . cnki . hxsj . 2023 . 0002 作者") == [
        "10.13822/j.cnki.hxsj.2023.0002"
    ]


def test_pdf_doi_does_not_join_arbitrary_words_or_relax_user_input():
    assert extract_pdf_dois("10.1000/target other words") == ["10.1000/target"]
    assert extract_pdf_dois("10.1000/target\n10.1000/other") == [
        "10.1000/target",
        "10.1000/other",
    ]
    with pytest.raises(ValueError):
        normalize_doi("10．13822 / j．cnki．hxsj．2023．0002")


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
