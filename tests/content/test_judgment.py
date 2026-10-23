"""The optional judge can advise without modifying canonical evidence."""

from copy import deepcopy
from pathlib import Path

import pytest

from aletheia_nexus.content import ReadingDecision, assess_reading
from aletheia_nexus.content.evidence import build_evidence_pack
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.content.service import parse_document


@pytest.fixture
def pack(tmp_path):
    pdf = register_local_pdf(
        Path(__file__).resolve().parents[2]
        / "benchmarks"
        / "v07_fixtures"
        / "native_article.pdf",
        output_dir=tmp_path,
        title="Synthetic evidence",
    )
    parse_document(pdf)
    return build_evidence_pack(tmp_path)


class Judge:
    name = "test-local-judge"
    version = "1"

    def __init__(self, decision):
        self.decision = decision

    def judge(self, request):
        self.request = request
        return self.decision


def assess(pack, judge):
    entry = pack["included"][0]
    return assess_reading(
        pack,
        judge,
        parsed_artifact_id=entry["parsed_artifact_id"],
        location_id=entry["review_locations"][0]["id"],
        question="Which reading agrees with the supplied source?",
    )


@pytest.mark.parametrize("outcome", ["prefer", "unresolved", "abstain"])
def test_provider_gets_context_and_returns_cited_advice_without_editing(pack, outcome):
    before = deepcopy(pack)
    bid = pack["included"][0]["review_locations"][0]["block_ids"][0]
    judge = Judge(ReadingDecision(outcome, (bid,), "Source-based explanation."))
    report = assess(pack, judge)
    assert report["advisory"] and report["outcome"] == outcome
    assert report["citations"][0]["block_id"] == bid
    assert report["citations"][0]["evidence"]["page"] >= 1
    assert judge.request["document"]["source"] == pack["included"][0]["source"]
    assert judge.request["document"]["blocks"] == pack["included"][0]["blocks"]
    judge.request["document"]["blocks"][0]["text"] = "edited by provider"
    report["citations"][0]["evidence"]["page"] = 999
    assert pack == before


@pytest.mark.parametrize(
    "decision",
    [
        ReadingDecision("prefer", ("invented-id",), "Unknown reference."),
        ReadingDecision("prefer", (), "No source."),
        ReadingDecision("abstain", (), ""),
        ReadingDecision("invalid", (), "Invalid outcome."),
    ],
)
def test_unknown_references_and_unsupported_decisions_are_rejected(pack, decision):
    with pytest.raises(ValueError):
        assess(pack, Judge(decision))


def test_provider_failure_does_not_create_a_decision_or_change_evidence(pack):
    before = deepcopy(pack)

    class FailedJudge(Judge):
        def judge(self, request):
            request["document"]["blocks"].clear()
            raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        assess(pack, FailedJudge(None))
    assert pack == before
