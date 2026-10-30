"""Table abbreviations reuse caption, geometry and namespace handling."""

import pytest
from test_segmented_grid_cells import segmented_page

from aletheia_nexus.content.captions import (
    _caption_description,
    _caption_match,
    _deduplicate_caption_blocks,
    _is_table_caption,
)
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.content.service import parse_document


@pytest.mark.parametrize(
    ("text", "label", "description"),
    [
        ("Tab. 2. Instrument readings", "2", "Instrument readings"),
        ("Supplementary Tab. S3 | Instrument readings", "S3", "Instrument readings"),
        ("SUPPLEMENTARY TAB. IV: Values and units", "IV", "Values and units"),
    ],
)
def test_abbreviation_retains_original_text_label_and_description(
    text, label, description
):
    match = _caption_match(text)
    assert _is_table_caption(match)
    assert match["label"] == label
    assert _caption_description(text, match) == description


@pytest.mark.parametrize(
    "text",
    [
        "Tab. 2 shows the measured response.",
        "Supplementary Tab. 2 lists the parameters.",
        "Tab. 2, 3 show the data.",
        "Tab. II–IV provide the parameters.",
        "Tab. 2 and Tab. 3 show the data.",
        "Tab 2. Navigation control",
        "Tab2. Navigation control",
    ],
)
def test_abbreviation_keeps_prose_and_nonperiod_tab_excluded(text):
    assert _caption_match(text) is None


def test_abbreviation_deduplicates_table_alias_without_crossing_namespace():
    texts = [
        "Table 1. Instrument readings",
        "Tab. 1. Instrument readings",
        "Supplementary Tab. 1. Instrument readings",
    ]
    blocks = [
        dict(id=f"b{i}", page=1, kind="caption", text=text)
        for i, text in enumerate(texts)
    ]
    _deduplicate_caption_blocks(blocks)
    assert [b["kind"] for b in blocks] == ["caption", "paragraph", "caption"]
    assert [b["text"] for b in blocks] == texts


@pytest.mark.parametrize("prefix", ["Tab.", "Supplementary Tab."])
def test_abbreviated_caption_uses_existing_painted_table_cells(tmp_path, prefix):
    title = prefix + " 1. Wrapped instrument readings"
    writer, _ = segmented_page(caption=title)
    pdf = tmp_path / "table.pdf"
    writer.write(pdf)
    local = register_local_pdf(
        pdf, output_dir=tmp_path / "library", title="Self-authored abbreviated caption"
    )
    doc = parse_document(local).document
    assert not doc["errors"]
    assert len(doc["tables"]) == 1 and not doc["figures"]
    table = doc["tables"][0]
    assert title in table["caption"]
    assert (table["row_count"], table["column_count"]) == (4, 3)
    cells = {c["text"]: c for c in table["cells"]}
    assert cells["Readings"]["column_span"] == 2
    for fragment in ("12.", "3"):
        assert (cells[fragment]["row"], cells[fragment]["column"]) == (3, 2)
    assert not any(c["text"] == "12.3" for c in table["cells"])
