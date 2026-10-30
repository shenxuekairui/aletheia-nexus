"""Scientific title markup changes presentation, never bibliographic evidence."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from aletheia_nexus.core.organization import filename_stem
from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.scientific_text import scientific_filename_text
from aletheia_nexus.workbench.ui_acquisition import AcquisitionPage


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ti<sup>3+</sup> self-doped TiO<sub>2</sub>", "Ti3+ self-doped TiO2"),
        ("Ti&lt;sup&gt;3+&lt;/sup&gt; / CO&lt;sub&gt;2&lt;/sub&gt;", "Ti3+ / CO2"),
        ("Catalysis Science &amp; Technology", "Catalysis Science & Technology"),
        ("Fe&#179;&#43; &rarr; Fe&#178;&#43;", "Fe³+ → Fe²+"),
        (
            '<jats:italic>Ti<jats:sup>3+</jats:sup></jats:italic> and CO<sub class="formula">2</sub>',
            "Ti3+ and CO2",
        ),
        ("<b>Ni</b><span lang='en'>–Fe</span> <em>in situ</em>", "Ni–Fe in situ"),
        ("<italic>Operando</italic> <bold>CO</bold><sub>2</sub>", "Operando CO2"),
        ("CO<sub>2</sub><br/>reduction<wbr>test", "CO2 reduction test"),
        ("A < 2 and B > 5; x&lt;y&gt;z; E<3", "A < 2 and B > 5; x<y>z; E<3"),
        ("A < b > C and A<b>C", "A < b > C and A<b>C"),
        ("unmatched <sup>2 and </sub> literal", "unmatched <sup>2 and </sub> literal"),
        (
            "unknown <chemical>CO2</chemical> <math>x<y</math>",
            "unknown <chemical>CO2</chemical> <math>x<y</math>",
        ),
    ],
)
def test_known_markup_flattens_without_dropping_scientific_text_or_math(raw, expected):
    assert scientific_filename_text(raw) == expected


def fixture(tmp_path):
    source = tmp_path / "incoming.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    with source.open("wb") as stream:
        writer.write(stream)
    library = LibraryService(tmp_path / "library")
    paper = library.import_pdf(
        source, title="Ti<sup>3+</sup> doped TiO<sub>2</sub>", folder="original"
    )
    library.update_metadata(
        paper["id"],
        year=2024,
        journal="ChemistrySelect &amp; Research",
        authors=["<i>A. Author</i>"],
        title_zh="Ti<sup>3+</sup>自掺杂TiO<sub>2</sub> &amp; CO<sub>2</sub>还原",
        custom_name="<b>自定义</b> &amp; 标题",
        translation={"confirmed": True, "source": "manual"},
    )
    attachment = tmp_path / "data.csv"
    attachment.write_text("name,value\nCO2,1\n", encoding="utf-8")
    library.import_attachment(paper["id"], attachment)
    return library, library.get(paper["id"])


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        (
            "{year}-{journal}-{title_zh}",
            "2024-ChemistrySelect & Research-Ti3+自掺杂TiO2 & CO2还原",
        ),
        ("{title_original}", "Ti3+ doped TiO2"),
        ("{first_author}-{custom_name}", "A. Author-自定义 & 标题"),
    ],
)
def test_existing_rename_preview_and_transaction_share_plain_base_with_si(
    tmp_path, template, expected
):
    library, paper = fixture(tmp_path)
    metadata = deepcopy(paper["metadata"])
    originals = {
        "pdf": Path(paper["pdf_path"]).read_bytes(),
        "source": Path(paper["sidecar_path"]).read_bytes(),
        "si": Path(paper["attachments"][0]["path"]).read_bytes(),
    }
    preview = library.preview_rename([paper["id"]], template, folder="target")
    planned = preview["items"][0]
    assert planned["base_name"] == expected
    assert planned["translation_source"] == "confirmed"
    assert Path(paper["pdf_path"]).is_file()  # Preview is not an automatic rename.
    assert library.get(paper["id"])["metadata"] == metadata
    operation = library.execute_rename(preview)
    assert operation["status"] == "COMPLETED"
    current = library.get(paper["id"])
    assert current["id"] == paper["id"] and current["metadata"] == metadata
    assert current["title_original"] == paper["title_original"]
    assert current["title_zh"] == paper["title_zh"]
    assert Path(current["pdf_path"]).name == expected + ".pdf"
    assert Path(current["attachments"][0]["path"]).name == expected + "__SI-01.csv"
    assert Path(current["attachments"][0]["path"]).parent == library.root / "target/SI"
    assert Path(current["pdf_path"]).read_bytes() == originals["pdf"]
    assert Path(current["sidecar_path"]).read_bytes() == originals["source"]
    assert Path(current["attachments"][0]["path"]).read_bytes() == originals["si"]
    assert library.rollback(operation["id"])["status"] == "ROLLED_BACK"
    restored = library.get(paper["id"])
    assert restored["pdf_path"] == paper["pdf_path"]
    assert restored["metadata"] == metadata


def test_missing_translation_falls_back_to_rendered_original_and_math_is_not_lost(
    tmp_path,
):
    library, paper = fixture(tmp_path)
    library.update_metadata(paper["id"], custom_name="A < 2 and B > 5")
    plan = library.preview_rename([paper["id"]], "{custom_name}")
    assert plan["items"][0]["base_name"] == filename_stem("A < 2 and B > 5")
    assert "2 and B" in plan["items"][0]["base_name"]
    # Independent paper without a translated title follows the same renderer.
    writer = PdfWriter()
    writer.add_blank_page(width=210, height=300)
    other_pdf = tmp_path / "other-incoming.pdf"
    with other_pdf.open("wb") as stream:
        writer.write(stream)
    other = library.import_pdf(
        other_pdf, title="CO<sub>2</sub> reduction", folder="other"
    )
    fallback = library.preview_rename([other["id"]], "{title_zh}")
    assert fallback["items"][0]["base_name"] == "CO2 reduction"
    assert "title_zh" in fallback["items"][0]["missing_metadata"]
    assert library.get(other["id"])["title_original"] == "CO<sub>2</sub> reduction"


def test_acquisition_per_item_automatic_naming_uses_same_rendering_without_translation(
    tmp_path,
):
    library, paper = fixture(tmp_path)
    source_bytes = Path(paper["sidecar_path"]).read_bytes()

    class Acquisition:
        def run(self, requests, options, *, context, checkpoint_path, on_item):
            row = {
                "id": "engineering-fixture",
                "status": "VERIFIED",
                "pdf": paper["pdf_path"],
                "request": {},
            }
            return {"status": "COMPLETED", "items": [on_item(row)]}

    def unexpected(*_, **__):
        pytest.fail("Naming must not trigger a model or parser request")

    page = AcquisitionPage()
    page.ctx = SimpleNamespace(
        library=library,
        acquisition=Acquisition(),
        translation=SimpleNamespace(translate=unexpected),
        research=SimpleNamespace(parse=unexpected),
    )
    context = SimpleNamespace(
        checkpoint=lambda: None,
        progress=lambda *_, **__: None,
        record=lambda *_, **__: None,
    )
    report = page.acquisition_worker(
        [], {"include_si": True}, {"template": "{year}-{journal}-{title_zh}"}
    )(context)
    assert report["status"] == "COMPLETED"
    current = library.get(paper["id"])
    assert "_sup_" not in Path(current["pdf_path"]).name
    assert "_sub_" not in Path(current["pdf_path"]).name
    assert "&amp;" not in Path(current["pdf_path"]).name
    assert Path(current["pdf_path"]).name.startswith(
        "2024-ChemistrySelect & Research-Ti3+"
    )
    assert Path(current["sidecar_path"]).read_bytes() == source_bytes
    assert current["title_zh"] == paper["title_zh"]
