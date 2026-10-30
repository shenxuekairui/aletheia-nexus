"""Exercise actual NiceGUI reader widgets; no PDF renderer or browser required."""

from types import SimpleNamespace

import pytest


def test_physical_page_callback_updates_links_image_and_citation_label(monkeypatch):
    pytest.importorskip("nicegui")
    from nicegui import ui
    from nicegui.elements.image import Image

    from aletheia_nexus.workbench.ui import WorkbenchUI

    monkeypatch.setattr("aletheia_nexus.workbench.ui.guard", lambda f: f)
    monkeypatch.setattr("shutil.which", lambda _: "renderer-present")
    source = SimpleNamespace(
        pdf="paper.pdf",
        verify=lambda: None,
        identity={
            "page_count": 6,
            "document_role": "SUPPLEMENT",
            "identity_basis": "DECLARED",
            "title": "Self-authored reader fixture",
        },
    )
    context = SimpleNamespace(
        research=SimpleNamespace(
            app=SimpleNamespace(check_document=lambda *args: source)
        )
    )
    controller = WorkbenchUI(
        context, SimpleNamespace(register=lambda _: "/an-file/explicit-token")
    )
    before = set(ui.context.client.elements)
    controller.show_pdf({"id": "si"}, page=3)
    elements = [e for key, e in ui.context.client.elements.items() if key not in before]
    button = next(e for e in elements if getattr(e, "text", "") == "下一页")
    handler = next(
        v.handler for v in button._event_listeners.values() if v.type == "click"
    )
    handler(None)
    links = {e.text: e._props["href"] for e in elements if "href" in e._props}
    assert links["在新标签页打开 PDF"].endswith("#page=4&view=FitH")
    assert links["在新标签页放大原页图像"].endswith("explicit-token/4")
    image = next(e for e in elements if isinstance(e, Image))
    assert image._props["src"].endswith("explicit-token/4")
    page = next(e for e in elements if e._props.get("label") == "物理页码")
    assert page.value == 4
    assert any(
        "当前物理第 4 页 / 6" in getattr(e, "text", "") and "初始引用第 3 页" in e.text
        for e in elements
    )
    # Navigating a supplement never borrows the main paper's page numbering.
    handler(None)
    handler(None)
    assert page.value == 6 and not button.enabled
