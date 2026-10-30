import pytest
from test_research import research as research_fixture


@pytest.fixture(name="research")
def source_fixture(tmp_path):
    yield from research_fixture.__wrapped__(tmp_path)


def test_skip_is_a_durable_file_boundary_and_finished_count_reaches_total(research):
    class Context:
        updates = []
        records = []

        def checkpoint(self):
            pass

        def should_skip(self, item_id):
            return item_id == "p1"

        def progress(self, current, total, **details):
            self.updates.append((current, total, details))

        def record(self, item_id, status, **details):
            self.records.append((item_id, status))

    context = Context()
    result = research.parse(["p1", "p2"], context=context)
    assert result["status"] == "PARTIAL"
    assert context.records == [("p1", "SKIPPED"), ("p2", "PARSED")]
    assert context.updates[-1][:2] == (2, 2)
    assert not research.versions("p1")[0]["versions"]
    assert research.versions("p2")[0]["versions"]
