"""First-use navigation never starts acquisition, parsing, or model work."""

from pathlib import Path
from types import SimpleNamespace

from nicegui import ui

from aletheia_nexus.workbench.ui_home import GUIDE, HomePages, home_result_summary


class Page(HomePages):
    def __init__(self, root, papers=(), jobs=()):
        self.calls = []
        self.ctx = SimpleNamespace(
            library=SimpleNamespace(
                root=Path(root),
                scan=lambda: {"items": list(papers)},
                selection=lambda: [],
            ),
            jobs=SimpleNamespace(list=lambda: list(jobs)),
            research=SimpleNamespace(results=lambda: []),
        )

    def navigate(self, name):
        self.calls.append(("navigate", name))

    def settings_dialog(self):
        self.calls.append(("settings",))

    def import_dialog(self):
        self.calls.append(("import",))

    def guide_dialog(self):
        self.calls.append(("guide",))

    def task_dialog(self):
        self.calls.append(("tasks",))


def render(page):
    prior = set(ui.context.client.elements)
    page.home_page()
    return [
        element
        for key, element in ui.context.client.elements.items()
        if key not in prior
    ]


def click(elements, text):
    button = next(
        element
        for element in elements
        if getattr(element, "text", None) == text
        and getattr(element, "_event_listeners", {})
    )
    listener = next(
        item for item in button._event_listeners.values() if item.type == "click"
    )
    listener.handler(None)


def test_empty_library_has_short_path_with_existing_application_actions(tmp_path):
    page = Page(tmp_path)
    elements = render(page)
    assert "十分钟开始" in [getattr(e, "text", None) for e in elements]
    assert not page.calls  # Merely rendering the page starts no work.
    click(elements, "查看 / 更换文库")
    click(elements, "导入本地 PDF")
    click(elements, "打开文库并解析")
    click(elements, "打开科研检索")
    assert page.calls == [
        ("settings",),
        ("import",),
        ("navigate", "文献库"),
        ("navigate", "科研检索"),
    ]


def test_example_click_only_prefills_and_navigates_without_external_work(tmp_path):
    page = Page(tmp_path)
    elements = render(page)
    assert not hasattr(page, "acquisition_example_text")
    click(elements, "填入公开论文示例")
    assert page.acquisition_example_text == "10.1038/s41467-019-08805-x"
    assert page.calls == [("navigate", "获取论文")]


def test_existing_library_keeps_normal_overview_instead_of_first_use_steps(tmp_path):
    page = Page(tmp_path, papers=[{"parse_status": "PARSED", "si_count": 1}])
    elements = render(page)
    texts = [getattr(e, "text", None) for e in elements]
    assert "十分钟开始" not in texts
    assert "继续你的研究" in texts and "近期任务" in texts
    assert "文库论文" in texts and "研究成果" in texts


def test_empty_library_keeps_live_task_access_during_first_import(tmp_path):
    page = Page(tmp_path, jobs=[{"id": "import-first", "status": "RUNNING"}])
    elements = render(page)
    click(elements, "查看正在处理的 1 个任务")
    assert page.calls == [("tasks",)]


def test_guide_explains_explicit_groups_conflicts_and_clear_overrides():
    first = " ".join(GUIDE[0][2])
    acquisition = " ".join(
        next(paragraphs for name, _, paragraphs in GUIDE if name == "获取论文")
    )
    assert "解析已勾选" in first and "科研检索" in first
    assert "A. 羧酸还原" in acquisition and "### 羧酸还原" in acquisition
    assert "分类=/" in acquisition and "标签=[]" in acquisition
    assert "冲突" in acquisition and "统一设置" in acquisition


def test_recent_claim_comparison_shows_real_delivery_instead_of_zero_data(tmp_path):
    page = Page(tmp_path, papers=[{"parse_status": "PARSED"}])
    row = {
        "path": "comparison.result.json",
        "objective": "比较两篇文献",
        "comparison": True,
        "paper_count": 2,
        "records": 0,
        "claims": 5,
        "revisions": 0,
    }
    page.ctx.research.results = lambda: [row]
    elements = render(page)
    texts = [getattr(element, "text", "") for element in elements]
    assert "跨论文比较 · 2 篇 · 5 项主张 · 0 次修订" in texts
    assert not any("0 条结构化记录" in text for text in texts)
    click(elements, "继续核对")
    assert page.current_result == "comparison.result.json"
    assert page.calls == [("navigate", "研究成果")]


def test_empty_and_mixed_delivery_counts_are_truthful():
    assert (
        home_result_summary({"records": 0, "claims": 0, "revisions": 0})
        == "尚无已交付的数据或主张 · 0 次修订"
    )
    assert (
        home_result_summary({"records": 2, "claims": 3, "revisions": 1})
        == "2 条结构化记录 · 3 项主张 · 1 次修订"
    )


def test_guide_describes_claim_delivery_and_qualified_evidence_navigation():
    heading, paragraphs = next(
        (title, paragraphs) for name, title, paragraphs in GUIDE if name == "成果核对"
    )
    assert heading == "有引用的结果，可回到原文核对"
    content = " ".join(paragraphs)
    assert "主张型结果不显示空数据表" in content
    assert "文献1" in content and "专家区" in content
