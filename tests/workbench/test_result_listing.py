import pytest
from test_research import research as research_fixture


@pytest.fixture(name="research")
def source_fixture(tmp_path):
    yield from research_fixture.__wrapped__(tmp_path)


def test_shared_result_reader_lists_each_paper_under_a_common_goal(research):
    class Provider:
        identity = {"provider": "self-authored-local-fixture"}

        def generate(self, request, schema, images, budget, max_output_tokens):
            return {
                "records": [],
                "claims": [],
                "requests": [],
                "issues": [
                    {
                        "kind": "material_insufficient",
                        "detail": "Local mock; no scientific or network claim.",
                        "source_id": request["material"]["documents"][0]["id"],
                        "page": 1,
                    }
                ],
            }

    task = research.local_plan("Common task objective", ["p1", "p2"], mode="parsed")
    research.execute(task, consent=True, provider=Provider())
    rows = research.results()
    assert len(rows) == 2
    assert {r["title"] for r in rows} == {"Alpha catalysis", "Beta measurement"}
    assert {r["objective"] for r in rows} == {"Common task objective"}
    assert all(r["run"] for r in rows)


def test_native_comparison_projection_keeps_real_type_scope_and_claim_count(research):
    class Provider:
        identity = {"provider": "self-authored-local-fixture"}

        def generate(self, request, schema, images, budget, max_output_tokens):
            document = request["material"]["documents"][0]
            if request["phase"] == "cross_document_synthesis":
                block = document["blocks"][0]
                return {
                    "claims": [
                        {
                            "text": "Synthetic comparison delivery, not scientific scoring.",
                            "nature": "ai_synthesis",
                            "citations": [
                                {
                                    "source_id": document["id"],
                                    "block_id": block["id"],
                                    "page": block["page"],
                                    "quote": block["text"],
                                }
                            ],
                        }
                    ],
                    "issues": [],
                }
            return {
                "records": [],
                "claims": [],
                "requests": [],
                "issues": [
                    {
                        "kind": "material_insufficient",
                        "detail": "Local mock only.",
                        "source_id": document["id"],
                        "page": 1,
                    }
                ],
            }

    task = research.local_plan(
        "Mock cross-paper acceptance", ["p1", "p2"], mode="parsed"
    )
    task["synthesize"] = True
    research.execute(task, consent=True, provider=Provider())
    rows = research.results()
    comparison = next(row for row in rows if row["comparison"])
    assert comparison["paper_count"] == 2
    assert comparison["records"] == 0 and comparison["claims"] == 1
    assert research.read_result(comparison["path"])["comparison"] is True
    singles = [row for row in rows if not row["comparison"]]
    assert len(singles) == 2 and all(row["paper_count"] == 1 for row in singles)
