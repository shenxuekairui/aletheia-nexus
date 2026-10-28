import json
from copy import deepcopy

import httpx
import pytest

from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.workbench.translation import TITLE_PROMPT, TranslationService


class Library:
    def __init__(self):
        self.items = {
            "a": {"title": "Selective reduction of CO₂ on Cu(I)"},
            "b": {"title": "Oxidation of Fe(II)"},
        }

    def get(self, paper_id):
        return deepcopy(self.items[paper_id])

    def update_metadata(self, paper_id, **fields):
        self.items[paper_id].update(fields)
        return self.get(paper_id)


def response(translations):
    return httpx.Response(
        200,
        json={
            "status": "completed",
            "usage": {"input_tokens": 100, "output_tokens": 60},
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps({"translations": translations}),
                        }
                    ],
                }
            ],
        },
    )


def test_translation_ids_cache_confirmation_and_remote_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-test-key")
    calls = []

    def handler(request):
        data = json.loads(request.content)
        calls.append(data)
        assert data["instructions"].startswith(TITLE_PROMPT)
        assert "paper.pdf" not in request.content.decode()
        return response(
            [
                {"id": "b", "title": "Fe(II)的氧化"},
                {"id": "a", "title": "Cu(I)上CO₂的选择性还原"},
            ]
        )

    library = Library()
    service = TranslationService(
        library, tmp_path, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ProcessingError, match="consent"):
        service.translate(["a"])
    result = service.translate(["a", "b"], consent=True)
    assert result["status"] == "COMPLETED"
    assert result["accounted_cost"] == pytest.approx(0.00068)
    assert library.items["a"]["title"] == "Selective reduction of CO₂ on Cu(I)"
    assert library.items["a"]["title_zh"].startswith("Cu(I)")
    service.translate(["a", "b"])
    assert len(calls) == 1
    service.edit("a", "人工确认的译名", confirmed=True)
    service.translate(["a"], force=True, consent=True)
    assert library.items["a"]["title_zh"] == "人工确认的译名"
    assert len(calls) == 1
    assert "fake-test-key" not in "".join(
        p.read_text() for p in tmp_path.rglob("*.json")
    )


def test_wrong_or_duplicate_id_never_updates_titles(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-test-key")
    library = Library()
    service = TranslationService(
        library,
        tmp_path,
        transport=httpx.MockTransport(
            lambda r: response([{"id": "a", "title": "甲"}, {"id": "a", "title": "乙"}])
        ),
    )
    result = service.translate(["a", "b"], consent=True)
    assert all(r["status"] == "FAILED" for r in result["items"])
    assert all("title_zh" not in item for item in library.items.values())


def test_unknown_billing_stops_remainder_and_durable_reservation_exists(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-test-key")
    library = Library()
    calls = []

    def handler(request):
        calls.append(1)
        run = [
            p
            for p in (tmp_path / "translations").glob("*.json")
            if json.loads(p.read_text()).get("calls")
        ][-1]
        assert json.loads(run.read_text())["calls"][0]["status"] == "started"
        raise httpx.ReadTimeout("unknown billing")

    service = TranslationService(
        library, tmp_path, transport=httpx.MockTransport(handler)
    )
    result = service.translate(["a", "b"], {"batch_size": 1}, consent=True)
    assert len(calls) == 1
    assert result["billing_uncertain"]
    assert [r["status"] for r in result["items"]] == ["FAILED", "SKIPPED"]


def test_tiny_budget_blocks_http_and_manual_unconfirmed_is_preserved(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-test-key")
    service = TranslationService(
        Library(),
        tmp_path,
        transport=httpx.MockTransport(
            lambda r: pytest.fail("budget should block HTTP")
        ),
    )
    result = service.translate(["a"], {"max_cost": 0.0000001}, consent=True)
    assert result["items"][0]["error"] == "cost_budget_exhausted"
    service.edit("b", "人工编辑", confirmed=False)
    estimate = service.estimate(["b"])
    assert estimate["confirmed"] == ["b"]
    assert estimate["pending"] == []
    assert service.translate(["b"])["items"][0]["status"] == "PRESERVED_MANUAL"


def test_missing_token_details_keeps_billing_uncertain(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-test-key")

    def handler(request):
        body = response([{"id": "a", "title": "甲"}]).json()
        body["usage"] = {"total_tokens": 100}
        return httpx.Response(200, json=body)

    service = TranslationService(
        Library(), tmp_path, transport=httpx.MockTransport(handler)
    )
    result = service.translate(["a"], consent=True)
    assert result["billing_uncertain"]
    assert result["accounted_cost"] > 0


def test_other_languages_cannot_pollute_chinese_title_field(tmp_path):
    service = TranslationService(Library(), tmp_path)
    with pytest.raises(ValueError, match="简体中文和繁体中文"):
        service.translate(["a"], {"target_language": "en"})
    assert "title_zh" not in service.library.items["a"]
