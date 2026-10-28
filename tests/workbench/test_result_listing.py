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
