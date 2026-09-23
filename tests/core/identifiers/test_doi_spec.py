import json
from pathlib import Path

import pytest

from aletheia_nexus.core.identifiers import doi as doi_module

SPEC_FILE = Path(__file__).parents[2] / "data" / "doi_v0_2_spec_cases.json"

with SPEC_FILE.open(encoding="utf-8") as file:
    CASES = json.load(file)


EXCEPTION_TYPES = {
    "ValueError": ValueError,
    "TypeError": TypeError,
}


def _run_case(function_name, case):
    function = getattr(doi_module, function_name, None)

    assert callable(function), f"{function_name}() is not implemented"

    options = case.get("options", {})
    expected_exception = case.get("expected_exception")

    if expected_exception:
        exception_type = EXCEPTION_TYPES[expected_exception]

        with pytest.raises(exception_type):
            function(case["input"], **options)

        return

    result = function(case["input"], **options)

    assert result == case["expected"]


@pytest.mark.parametrize(
    "case",
    CASES["normalize_doi"],
    ids=lambda case: case["id"],
)
def test_normalize_doi_spec(case):
    _run_case("normalize_doi", case)


@pytest.mark.parametrize(
    "case",
    CASES["normalize_dois"],
    ids=lambda case: case["id"],
)
def test_normalize_dois_spec(case):
    _run_case("normalize_dois", case)


@pytest.mark.parametrize(
    "case",
    CASES["extract_dois"],
    ids=lambda case: case["id"],
)
def test_extract_dois_spec(case):
    _run_case("extract_dois", case)


@pytest.mark.parametrize(
    "case",
    CASES["looks_like_doi"],
    ids=lambda case: case["id"],
)
def test_looks_like_doi_spec(case):
    _run_case("looks_like_doi", case)
