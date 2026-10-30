import pytest

pytest.importorskip("nicegui")

from aletheia_nexus.workbench.ui_parameters import parameter_sections


def test_tiers_share_one_options_reader_and_atomic_preset_application():
    form = parameter_sections(
        {"ocr": False, "max_pages": 30, "ocr_dpi": 300, "heading_font_ratio": 1.35},
        common=("ocr", "max_pages"),
        advanced=("ocr_dpi",),
        expert=("heading_font_ratio",),
    )
    form.apply({"ocr": True, "ocr_dpi": 400, "heading_font_ratio": 1.5})
    assert form() == {
        "ocr": True,
        "max_pages": 30,
        "ocr_dpi": 400,
        "heading_font_ratio": 1.5,
    }
    before = form()
    with pytest.raises(ValueError):
        form.apply({"ocr": False, "heading_font_ratio": "bad number"})
    assert form() == before
    with pytest.raises(ValueError):
        form.apply({"api_key": "no"})
    assert form() == before
