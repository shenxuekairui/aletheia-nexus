"""Plain library projections leave editable and scientific metadata intact."""

from copy import deepcopy

from aletheia_nexus.workbench.ui_library import library_table_row, view_title


def test_all_title_display_modes_flatten_markup_without_changing_source_row():
    row = {
        "title_original": "Ti<sup>3+</sup> / TiO<sub>2</sub> &amp; CO<sub>2</sub>",
        "title_zh": "Ti<sup>3+</sup>自掺杂TiO<sub>2</sub> &amp; CO<sub>2</sub>还原",
        "custom_name": "<b>重点</b> &amp; 对照",
        "translation": {"source": "manual", "confirmed": True},
    }
    original = deepcopy(row)
    for mode, expected in {
        "bilingual": "Ti3+自掺杂TiO2 & CO2还原\nTi3+ / TiO2 & CO2",
        "zh": "Ti3+自掺杂TiO2 & CO2还原",
        "original": "Ti3+ / TiO2 & CO2",
        "custom": "重点 & 对照",
    }.items():
        assert view_title(row, {"title_mode": mode}) == expected
        assert row == original
    assert view_title({"title": "A < 2; x&lt;y&gt;z"}, {}) == "A < 2; x<y>z"


def test_table_original_chinese_and_journal_columns_are_plain_without_mutating_row():
    row = {
        "id": "paper_original_source",
        "pdf_path": "/library/unchanged.pdf",
        "title_original": "CO<sub>2</sub> &amp; Ti<sup>3+</sup>",
        "title_zh": "CO<sub>2</sub> 与 Ti<sup>3+</sup>",
        "journal": "<i>Catalysis Science</i> &amp; Technology",
        "tags": [],
        "authors": ["Original author"],
        "collections": [],
        "metadata": {"translation": {"confirmed": True}},
    }
    original = deepcopy(row)
    projected = library_table_row(row, view_title(row, {}))
    assert projected["title"] == "CO2 与 Ti3+\nCO2 & Ti3+"
    assert projected["title_original"] == "CO2 & Ti3+"
    assert projected["title_zh"] == "CO2 与 Ti3+"
    assert projected["journal"] == "Catalysis Science & Technology"
    assert projected["id"] == row["id"]
    assert projected["path"] == row["pdf_path"]
    assert row == original
