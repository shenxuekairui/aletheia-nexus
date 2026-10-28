"""Claim-only/comparison results have real readable delivery, not an empty table."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from aletheia_nexus.workbench.labels import value_label
from aletheia_nexus.workbench.ui_research import (
    ResearchPages,
    citation_button_text,
    display_claim_text,
    result_source_names,
    result_version_label,
)


def test_comparison_version_label_is_not_the_first_paper_or_zero_record_placeholder():
    row = {
        "title": "First paper / Second paper",
        "objective": "A comparison",
        "comparison": True,
        "paper_count": 2,
        "records": 0,
        "claims": 5,
        "revisions": 0,
        "run": "native-run",
    }
    label = result_version_label(row)
    assert "跨论文比较 · 2 篇" in label and "5 项主张" in label
    assert "First paper" not in label and "0 条" not in label
    assert value_label("ai_synthesis") == "AI综合判断"
    assert value_label("author_interpretation") == "作者解释"


def test_citation_label_uses_verified_title_and_retains_raw_id_in_tooltip():
    citation = {"source_id": "attachment_long_audit_id", "page": 7}
    sources = {
        citation["source_id"]: {
            "title": "A very long actual source title " * 3,
            "document_role": "SUPPLEMENT",
        }
    }
    label, tooltip = citation_button_text(citation, sources)
    assert "A very long actual source title" in label and "SI" in label
    assert "物理第7页" in label and "attachment_" not in label
    assert (
        citation["source_id"] in tooltip
        and sources[citation["source_id"]]["title"] in tooltip
    )
    unknown, _ = citation_button_text({"source_id": "missing", "page": 1}, sources)
    assert "未匹配来源" in unknown


def test_reading_aliases_use_only_exact_known_sources_and_current_matched_metadata():
    sources = [
        {
            "id": "paper_1",
            "identity": {
                "title": "Original first title",
                "document_role": "ARTICLE",
                "pdf_sha256": "hash1",
                "article_id": "doi:first",
            },
        },
        {
            "id": "si_1",
            "identity": {
                "title": "Original SI title",
                "document_role": "SUPPLEMENT",
                "parent": {"pdf_sha256": "hash1", "article_id": "doi:first"},
            },
        },
        {
            "id": "paper_2",
            "identity": {
                "title": "Original second title",
                "document_role": "ARTICLE",
                "pdf_sha256": "hash2",
                "article_id": "doi:second",
            },
        },
    ]
    paper_ids = {"paper_1": "current1", "si_1": "current1", "paper_2": "current2"}
    papers = {
        "current1": {"custom_name": "我的催化剂短名", "title_zh": "第一篇中文译名"},
        "current2": {"title_zh": "第二篇中文译名"},
    }
    before = deepcopy((sources, paper_ids, papers))
    aliases = result_source_names(sources, paper_ids, papers)
    assert aliases["paper_1"] == {"reference": "文献1", "title": "我的催化剂短名"}
    assert aliases["si_1"]["reference"] == "文献1的SI1"
    assert aliases["paper_2"] == {"reference": "文献2", "title": "第二篇中文译名"}
    text = (
        "比较paper_1与paper_2，以及si_1；paper_1_extra、xpaper_1、paper_unknown不能改。"
    )
    assert (
        display_claim_text(text, aliases)
        == "比较文献1与文献2，以及文献1的SI1；paper_1_extra、xpaper_1、paper_unknown不能改。"
    )
    assert (sources, paper_ids, papers) == before
    button, tooltip = citation_button_text(
        {"source_id": "paper_1", "page": 2},
        {s["id"]: s["identity"] for s in sources},
        aliases=aliases,
    )
    assert "文献1" in button and "我的催化剂短名" in button
    assert "Original first title" in tooltip and "paper_1" in tooltip


def test_unmapped_historical_source_uses_original_title_and_does_not_guess_parent():
    sources = [
        {
            "id": "paper_1",
            "identity": {"title": "Original title", "document_role": "ARTICLE"},
        },
        {
            "id": "si_1",
            "identity": {"title": "Unmatched SI", "document_role": "SUPPLEMENT"},
        },
    ]
    aliases = result_source_names(sources, {}, {})
    assert aliases["paper_1"]["title"] == "Original title"
    assert aliases["si_1"]["reference"].startswith("补充材料")


@pytest.mark.parametrize("kind", ["claims", "empty", "records"])
def test_real_result_widgets_skip_empty_table_and_keep_citations_linked_to_exact_source(
    tmp_path, monkeypatch, kind
):
    pytest.importorskip("nicegui")
    from nicegui import ui

    from aletheia_nexus.workbench import ui_research

    source_id = "paper_original_audit_identity"
    citation = {"source_id": source_id, "page": 1, "quote": "Original words"}
    result = {
        "task": {
            "objective": "Only UI delivery verification",
            "fields": [{"id": "material", "label": "材料", "type": "string"}],
        },
        "response": {"records": [], "claims": [], "issues": [], "requests": []},
        "sources": [
            {
                "id": source_id,
                "identity": {
                    "title": "Actual source paper title",
                    "document_role": "ARTICLE",
                },
            }
        ],
        "history": [],
        "provider": {"provider": "local mock"},
        "validation": {"record_states": {}},
    }
    if kind == "claims":
        result["response"]["claims"] = [
            {
                "text": f"Original claim containing {source_id} must remain literal.",
                "nature": "ai_synthesis",
                "citations": [citation],
            }
        ]
    elif kind == "records":
        result["response"]["records"] = [
            {
                "id": "r1",
                "subject": "A material",
                "fields": {
                    "material": {
                        "value": "Cu",
                        "unit": None,
                        "status": "reported",
                        "citations": [citation],
                    }
                },
            }
        ]
    before_result = deepcopy(result)
    table_calls, shown = [], []

    def table(rows, **kwargs):
        table_calls.append(deepcopy(rows))
        return SimpleNamespace(selected=[])

    class Controller(ResearchPages):
        current_result = "result.json"

        def title(self, *_):
            pass

        def show_pdf(self, document, *, page, container):
            shown.append((document, page))

    monkeypatch.setattr(ui_research, "rows_table", table)
    monkeypatch.setattr(ui_research, "guard", lambda callback: callback)
    controller = Controller()
    controller.page_content = SimpleNamespace(refresh=lambda: None)
    controller.ctx = SimpleNamespace(
        research=SimpleNamespace(
            results=lambda: [
                {
                    "path": "result.json",
                    "title": "Actual source paper title",
                    "objective": "UI test",
                    "comparison": False,
                    "paper_count": 1,
                    "records": len(result["response"]["records"]),
                    "claims": len(result["response"]["claims"]),
                    "revisions": 0,
                    "run": "mock-run",
                }
            ],
            read_result=lambda path: result,
            result_material_papers=lambda path: {},
            citation_document=lambda path, selected_id: {"pdf": selected_id + ".pdf"},
        )
    )
    old = set(ui.context.client.elements)
    controller.results_page()
    elements = [
        element for key, element in ui.context.client.elements.items() if key not in old
    ]
    texts = [getattr(element, "text", "") for element in elements]
    if kind == "records":
        assert len(table_calls) == 1 and table_calls[0][0]["value"] == "Cu"
    else:
        assert table_calls == []
        assert "核对选中数据的证据" not in texts
    if kind == "claims":
        assert any("本结果以研究主张交付" in text for text in texts)
        assert any("主张 1 · AI综合判断" == text for text in texts)
        button = next(
            element
            for element in elements
            if getattr(element, "text", "").startswith(
                "核对 文献1 · Actual source paper title"
            )
        )
        assert source_id not in button.text
        handler = next(
            listener.handler
            for listener in button._event_listeners.values()
            if listener.type == "click"
        )
        handler(None)
        assert shown == [({"pdf": source_id + ".pdf"}, 1)]
        assert (
            display_claim_text(
                result["response"]["claims"][0]["text"],
                {source_id: {"reference": "文献1"}},
            )
            in texts
        )
    elif kind == "empty":
        assert any("没有可展示的研究数据或主张" in text for text in texts)
    assert result == before_result
