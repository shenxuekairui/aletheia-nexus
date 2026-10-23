"""Regression cases for scientific symbols and differing OCR measurements."""

import pytest
from fontTools.encodings.StandardEncoding import StandardEncoding
from fontTools.misc import eexec
from fontTools.misc.psCharStrings import T1CharString
from fontTools.t1Lib import T1Font, findEncryptedChunks
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from aletheia_nexus.content.backends import (
    AdaptiveOcrBackend,
    LayoutPdfBackend,
    TesseractOcrBackend,
    TesseractOcrConfig,
)
from aletheia_nexus.content.backends.font_symbols import _outline_symbol
from aletheia_nexus.content.backends.tesseract import _parse_tsv
from aletheia_nexus.content.models import LayoutLine, PageLayout, PageObject


def symbol_page(
    *, mapped=False, broken=False, embedded_zero=False, omit_subrs=False, m_program=None
):
    # Self-authored Type 1 font. The glyph name deliberately differs from T0.
    font = object.__new__(T1Font)
    font.encoding = "ascii"
    font.font = {
        "FontName": "ANCustomSymbols",
        "FontType": 1,
        "PaintType": 0,
        "FontMatrix": [0.001, 0, 0, 0.001, 0, 0],
        "FontBBox": [0, 0, 800, 800],
        "Encoding": list(StandardEncoding),
        "Private": {
            "RD": ("string", "currentfile", "exch", "readstring", "pop"),
            "ND": ("noaccess", "def"),
            "NP": ("noaccess", "put"),
            "BlueValues": [],
            "lenIV": 4,
            "Subrs": [],
        },
        "CharStrings": {
            ".notdef": T1CharString(program=[0, 600, "hsbw", "endchar"]),
            "C42": T1CharString(
                program=[
                    0,
                    600,
                    "hsbw",
                    50,
                    230,
                    "rmoveto",
                    500,
                    0,
                    "rlineto",
                    0,
                    40,
                    "rlineto",
                    -500,
                    0,
                    "rlineto",
                    "closepath",
                    "endchar",
                ]
            ),
        },
    }
    if embedded_zero:
        font.font["Encoding"][0] = "C42"
    if m_program is not None:
        font.font["CharStrings"]["m"] = T1CharString(program=m_program)
    program = DecodedStreamObject()
    program.set_data(b"damaged" if broken else font.getData())
    if omit_subrs and not broken:
        # The Type 1 writer only closes Private correctly when Subrs exists.
        # Remove the empty definition from the encrypted fixture after writing.
        chunks = []
        for encrypted, chunk in findEncryptedChunks(program.get_data()):
            if encrypted:
                plain, _ = eexec.decrypt(chunk, 55665)
                assert b"/Subrs 0 array\ndef\n" in plain
                plain = plain.replace(b"/Subrs 0 array\ndef\n", b"", 1)
                chunk, _ = eexec.encrypt(plain, 55665)
            chunks.append(chunk)
        program.set_data(b"".join(chunks))
    if embedded_zero and not broken:
        program[NameObject("/Length1")] = NumberObject(
            program.get_data().index(b"currentfile eexec ") + len(b"currentfile eexec ")
        )
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    definition = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/ANCustomSymbols"),
            NameObject("/FirstChar"): NumberObject(64),
            NameObject("/LastChar"): NumberObject(64),
            NameObject("/Widths"): ArrayObject([NumberObject(600)]),
            NameObject("/Encoding"): DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Encoding"),
                    NameObject("/Differences"): ArrayObject(
                        [NumberObject(64), NameObject("/C42")]
                    ),
                }
            ),
            NameObject("/FontDescriptor"): DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/FontDescriptor"),
                    NameObject("/FontName"): NameObject("/ANCustomSymbols"),
                    NameObject("/Flags"): NumberObject(4),
                    NameObject("/FontBBox"): ArrayObject(
                        [NumberObject(x) for x in [0, 0, 800, 800]]
                    ),
                    NameObject("/Ascent"): NumberObject(800),
                    NameObject("/Descent"): NumberObject(0),
                    NameObject("/FontFile"): writer._add_object(program),
                }
            ),
        }
    )
    if embedded_zero:
        del definition[NameObject("/Encoding")]
        definition[NameObject("/FirstChar")] = NumberObject(0)
        definition[NameObject("/LastChar")] = NumberObject(0)
    if mapped:
        cmap = DecodedStreamObject()
        code = b"00" if embedded_zero else b"40"
        cmap.set_data(
            b"begincmap 1 begincodespacerange <00> <ff> endcodespacerange "
            b"1 beginbfchar <" + code + b"> <0040> endbfchar endcmap"
        )
        definition[NameObject("/ToUnicode")] = writer._add_object(cmap)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): definition})}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 12 Tf 50 700 Td <00> Tj ET"
        if embedded_zero
        else b"BT /F1 12 Tf 50 700 Td (@) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    if m_program is not None:
        definition[NameObject("/Encoding")] = NameObject("/WinAnsiEncoding")
        definition[NameObject("/FirstChar")] = NumberObject(109)
        definition[NameObject("/LastChar")] = NumberObject(109)
        cmap = DecodedStreamObject()
        cmap.set_data(b"begincmap 1 beginbfchar <6d> <006d> endbfchar endcmap")
        definition[NameObject("/ToUnicode")] = writer._add_object(cmap)
        page["/Resources"]["/Font"][NameObject("/FR")] = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        stream.set_data(
            b"BT /FR 12 Tf 50 700 Td (0.4) Tj /F1 12 Tf (m) Tj /FR 12 Tf ( solution; 3.7 ) Tj /F1 12 Tf (m) Tj /FR 12 Tf (m particles; ) Tj /F1 12 Tf (m) Tj /FR 12 Tf ( prose; 5 mm) Tj ET"
        )
    return page


def test_embedded_outline_recovers_custom_minus_without_modifying_pdf():
    page = symbol_page()
    original = page["/Contents"].get_data()
    layout = LayoutPdfBackend().extract_page(page, 1)
    assert [line.text for line in layout.lines] == ["−"]
    assert layout.lines[0].uncertain
    assert "NATIVE_FONT_SYMBOL_RECOVERED" in {w["code"] for w in layout.warnings}
    assert page["/Contents"].get_data() == original
    assert "/ToUnicode" not in page["/Resources"]["/Font"]["/F1"]


def test_explicit_unicode_mapping_is_not_guessed_from_shape():
    line = LayoutPdfBackend().extract_page(symbol_page(mapped=True), 1).lines[0]
    assert line.text == "@"


@pytest.mark.parametrize("omit_subrs", [False, True])
def test_type1_builtin_zero_encoding_preserves_missing_minus(omit_subrs):
    page = symbol_page(embedded_zero=True, omit_subrs=omit_subrs)
    original = page["/Contents"].get_data()
    layout = LayoutPdfBackend().extract_page(page, 1)
    assert [line.text for line in layout.lines] == ["−"]
    assert layout.lines[0].uncertain
    assert "NATIVE_FONT_SYMBOL_RECOVERED" in {w["code"] for w in layout.warnings}
    assert page["/Contents"].get_data() == original
    mapped = LayoutPdfBackend().extract_page(
        symbol_page(embedded_zero=True, omit_subrs=omit_subrs, mapped=True), 1
    )
    assert [line.text for line in mapped.lines] == ["@"]


def test_unreadable_custom_font_preserves_uncertain_fallback():
    line = LayoutPdfBackend().extract_page(symbol_page(broken=True), 1).lines[0]
    assert line.text == "@"
    assert line.uncertain


def test_double_waves_are_approximate_not_equals():
    wave = [
        ("moveTo", ((50, 200),)),
        ("curveTo", ((180, 200), (300, 380), (550, 380))),
        ("curveTo", ((570, 380), (570, 350), (550, 350))),
        ("curveTo", ((300, 350), (180, 170), (50, 170))),
        ("curveTo", ((30, 170), (30, 200), (50, 200))),
        ("closePath", ()),
    ]
    second = [(op, tuple((x, y + 260) for x, y in points)) for op, points in wave]
    assert _outline_symbol(wave + second, 1000) == "≈"
    bar = [
        ("moveTo", ((50, 200),)),
        ("lineTo", ((550, 200),)),
        ("lineTo", ((550, 230),)),
        ("lineTo", ((50, 230),)),
        ("closePath", ()),
    ]
    assert (
        _outline_symbol(
            bar + [(op, tuple((x, y + 160) for x, y in points)) for op, points in bar],
            1000,
        )
        is None
    )
    assert (
        _outline_symbol(
            [(op, tuple((x, y - 220) for x, y in points)) for op, points in bar], 1000
        )
        is None
    )


def test_arrow_outline_is_not_rewritten_as_minus():
    outline = [
        ("moveTo", ((50, 230),)),
        ("lineTo", ((500, 230),)),
        ("lineTo", ((500, 215),)),
        ("lineTo", ((600, 250),)),
        ("lineTo", ((500, 285),)),
        ("lineTo", ((500, 270),)),
        ("lineTo", ((50, 270),)),
        ("closePath", ()),
    ]
    assert _outline_symbol(outline, 1000) is None


class StaticBackend:
    name = "test"
    version = "1"

    def __init__(self, text, confidence=0.98):
        self.lines = (
            ()
            if text is None
            else (
                LayoutLine(
                    text, 20, 400, 500, 420, 12, extraction_confidence=confidence
                ),
            )
        )

    def extract_page(self, page, number):
        return PageLayout(page=number, width=600, height=800, lines=self.lines)


@pytest.mark.parametrize(
    "first,second",
    [
        ("The reported yield was 90%", "The reported yield was 90"),
        ("The current was 90 mA", "The current was 90 A"),
        ("The current was 90 mA", "The current was 90 MA"),
        ("Potential -1.4 V vs RHE", "Potential 1.4 V vs RHE"),
        ("Current 90 mA cm-2", "Current 90 mA cm2"),
        ("Yield 80-85%", "Yield 80.85%"),
        ("Potential 1.4 V vs RHE", "Potential 1.4 V vs SHE"),
    ],
)
@pytest.mark.parametrize("native", [True, False])
def test_scientific_disagreements_keep_both_readings(first, second, native):
    initial = StaticBackend(first if native else None)
    engines = (
        (StaticBackend(second),)
        if native
        else (StaticBackend(first, 0.8), StaticBackend(second))
    )
    layout = AdaptiveOcrBackend(
        native_backend=initial, ocr_backends=engines
    ).extract_page(None, 1)
    assert [line.text for line in layout.lines] == [first, second]
    assert all(line.uncertain for line in layout.lines)


def test_numeric_spacing_and_unicode_minus_can_agree():
    native = StaticBackend("Potential −1.4 V.")
    engine = StaticBackend("Potential -1.4V")
    layout = AdaptiveOcrBackend(
        native_backend=native, ocr_backends=(engine,)
    ).extract_page(None, 1)
    assert len(layout.lines) == 1
    assert not layout.lines[0].uncertain


def test_low_confidence_number_is_not_hidden_by_confident_sentence():
    payload = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    for i in range(20):
        payload += f"5\t1\t1\t1\t1\t{i + 1}\t{i * 20}\t20\t18\t12\t{0 if i == 19 else 99}\t{'80%' if i == 19 else 'text'}\n"
    line = _parse_tsv(
        payload,
        page_number=1,
        page_width=600,
        page_height=800,
        image_width=600,
        image_height=800,
        engine_id="test",
    )[0]
    assert line.extraction_confidence > 0.9
    assert line.uncertain


def test_corrupt_hidden_text_yields_to_readable_ocr_but_original_is_retained():
    original = "The current density was \x00\x00\x00 mA cm\x00\x00 after treatment."
    recovered = "The current density was 120 mA cm-2 after treatment."
    layout = AdaptiveOcrBackend(
        native_backend=StaticBackend(original),
        ocr_backends=(StaticBackend(recovered, 0.97),),
    ).extract_page(None, 1)
    assert [line.text for line in layout.lines] == [recovered, original]
    assert layout.lines[0].content_region == "body"
    assert layout.lines[1].content_region == "native-alternative"
    assert all(line.uncertain for line in layout.lines)
    assert "OCR_PRIMARY_RECOVERED" in {w["code"] for w in layout.warnings}


def test_low_confidence_ocr_does_not_replace_corrupt_native_text():
    original = "Yield \x00\x00\x00 after treatment"
    layout = AdaptiveOcrBackend(
        native_backend=StaticBackend(original),
        ocr_backends=(StaticBackend("Yield 90% after treatment", 0.7),),
    ).extract_page(None, 1)
    assert layout.lines[0].text == original
    assert layout.lines[1].content_region == "ocr-alternative"


def test_high_confidence_chart_ocr_still_requires_visual_review():
    native = PageLayout(
        page=1,
        width=600,
        height=800,
        objects=(PageObject("image", "plot", bbox=(0.02, 0.45, 0.9, 0.65)),),
    )
    candidate = StaticBackend("Potential 0.4 0.2 0.0 V vs RHE", 0.99).extract_page(
        None, 1
    )
    lines, _ = AdaptiveOcrBackend()._merge(native, [candidate])
    assert lines[0].content_region == "figure"
    assert lines[0].uncertain


def test_changed_language_model_invalidates_backend_identity(tmp_path, monkeypatch):
    import aletheia_nexus.content.backends.tesseract as module

    monkeypatch.setattr(module, "_tool_version", lambda *a, **k: "test")
    (tmp_path / "eng.traineddata").write_bytes(b"model one")
    config = TesseractOcrConfig(tessdata_dir=str(tmp_path), detect_orientation=False)
    first_backend = TesseractOcrBackend(config)
    first = first_backend.execution_identity
    (tmp_path / "eng.traineddata").write_bytes(b"model two")
    second_backend = TesseractOcrBackend(config)
    second = second_backend.execution_identity
    assert first != second
    assert first_backend.evidence_engine_id != second_backend.evidence_engine_id
    assert str(tmp_path) not in str(second)
    assert second["configuration"]["tessdata_dir"] == "explicit"


def test_readable_native_prose_is_not_rechecked_by_gap_ocr():
    from dataclasses import replace

    text = "A readable born-digital paragraph reports a measured current of 25 mA and explains the measurement conditions."
    native = StaticBackend(text).extract_page(None, 1)
    native = replace(
        native, objects=(PageObject("image", "plot", bbox=(0.1, 0.1, 0.9, 0.3)),)
    )
    candidate = StaticBackend(text.replace("25", "2.5")).extract_page(None, 1)
    lines, warnings = AdaptiveOcrBackend()._merge(native, [candidate])
    assert len(lines) == 1 and lines[0].text == text
    assert not lines[0].uncertain
    assert not warnings


def test_scanned_hidden_layer_is_still_compared_despite_long_native_text():
    from dataclasses import replace

    text = "The scan has a hidden text layer. " * 3 + "Yield 25%."
    native = StaticBackend(text).extract_page(None, 1)
    native = replace(native, objects=(PageObject("image", "scan", bbox=(0, 0, 1, 1)),))
    candidate = StaticBackend(text.replace("25", "2.5")).extract_page(None, 1)
    lines, _ = AdaptiveOcrBackend()._merge(native, [candidate])
    assert len(lines) == 2
    assert all(line.uncertain for line in lines)


def test_targeted_formula_evidence_is_not_skipped_as_page_ocr():
    from dataclasses import replace

    text = "A readable born-digital paragraph reports a measured current of 25 mA and explains the measurement conditions."
    native = StaticBackend(text).extract_page(None, 1)
    candidate = StaticBackend(text.replace("25", "2.5")).extract_page(None, 1)
    candidate = replace(
        candidate,
        lines=(replace(candidate.lines[0], content_region="formula"),),
    )
    lines, warnings = AdaptiveOcrBackend()._merge(native, [candidate])
    assert len(lines) == 2 and all(line.uncertain for line in lines)
    assert any(w["code"] == "OCR_ENGINE_DISAGREEMENT" for w in warnings)


def test_ocr_combined_fragments_are_compared_as_one_spatial_reading():
    from dataclasses import replace

    native = PageLayout(
        page=1,
        width=600,
        height=800,
        lines=(
            LayoutLine("Yield", 20, 400, 100, 420, 12),
            LayoutLine("75%", 105, 400, 150, 420, 12),
        ),
    )
    candidate = replace(
        StaticBackend("Yield 75%").extract_page(None, 1),
        lines=(LayoutLine("Yield 75%", 20, 400, 150, 420, 12),),
    )
    lines, warnings = AdaptiveOcrBackend()._merge(native, [candidate])
    assert [line.text for line in lines] == ["Yield", "75%"]
    assert not any(line.uncertain for line in lines)
    assert not warnings


def test_exact_agreement_deduplicates_without_clearing_native_uncertainty():
    from dataclasses import replace

    native = StaticBackend("电 流 效 率 80%").extract_page(None, 1)
    native = replace(native, lines=(replace(native.lines[0], uncertain=True),))
    candidate = StaticBackend("电流效率 80%").extract_page(None, 1)
    lines, _ = AdaptiveOcrBackend()._merge(native, [candidate])
    assert len(lines) == 1 and lines[0].uncertain


def test_ocr_combined_headers_keeps_recovered_private_use_symbol():
    native = PageLayout(
        page=1,
        width=600,
        height=800,
        lines=(
            LayoutLine("Ｃｕ\ue011ＰＴＦＥ", 20, 200, 120, 220, 12, uncertain=True),
            LayoutLine("Zn", 140, 200, 180, 220, 12),
        ),
    )
    candidate = PageLayout(
        page=1,
        width=600,
        height=800,
        lines=(
            LayoutLine(
                "Cu-PTFE Zn",
                20,
                200,
                180,
                220,
                12,
                extraction_confidence=0.95,
                source_engines=("ocr",),
            ),
        ),
    )
    lines, _ = AdaptiveOcrBackend()._merge(native, [candidate])
    assert any(line.text == "Cu-PTFE Zn" for line in lines)
    assert any(line.text == "Ｃｕ\ue011ＰＴＦＥ" for line in lines)


@pytest.mark.parametrize(
    "replacement,confidence,accepted", [("92%", 95, True), ("92%", 72, False)]
)
def test_short_line_retry_preserves_original_and_requires_clear_improvement(
    tmp_path, monkeypatch, replacement, confidence, accepted
):
    import subprocess

    import aletheia_nexus.content.backends.tesseract as module

    Image = pytest.importorskip("PIL.Image")

    monkeypatch.setattr(module, "_tool_version", lambda *a, **k: "test")
    monkeypatch.setattr(
        module.TesseractOcrBackend, "_traineddata_identity", lambda *a: {}
    )
    payload = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        + f"5\t1\t1\t1\t1\t1\t12\t12\t80\t20\t{confidence}\t{replacement}\n"
    )
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=payload)

    monkeypatch.setattr(module, "_run", run)
    backend = TesseractOcrBackend(
        TesseractOcrConfig(tessdata_dir=str(tmp_path), detect_orientation=False)
    )
    original = LayoutLine("N%", 20, 200, 100, 220, 12, extraction_confidence=0.62)
    result = backend._retry_short_lines(
        Image.new("L", (600, 800), 255), (original,), tmp_path, 600, 800
    )
    assert len(calls) == 1
    if accepted:
        assert result[0].text == replacement and result[0].uncertain
        assert result[0].x0 == pytest.approx(16)
        assert result[0].y0 == pytest.approx(214)
        assert result[0].x1 == pytest.approx(56)
        assert result[0].y1 == pytest.approx(224)
        assert result[1].text == original.text
        assert result[1].content_region == "ocr-alternative"
    else:
        assert result == (original,)


def test_short_line_retry_failure_keeps_positioned_evidence(tmp_path, monkeypatch):
    import aletheia_nexus.content.backends.tesseract as module

    Image = pytest.importorskip("PIL.Image")

    monkeypatch.setattr(module, "_tool_version", lambda *a, **k: "test")
    monkeypatch.setattr(
        module.TesseractOcrBackend, "_traineddata_identity", lambda *a: {}
    )

    def fail(*args, **kwargs):
        raise RuntimeError("OCR command timed out")

    monkeypatch.setattr(module, "_run", fail)
    backend = TesseractOcrBackend(TesseractOcrConfig(detect_orientation=False))
    original = LayoutLine(
        "8%", 20, 200, 100, 220, 12, extraction_confidence=0.62, uncertain=True
    )
    assert backend._retry_short_lines(
        Image.new("L", (600, 800), 255), (original,), tmp_path, 600, 800
    ) == (original,)


@pytest.mark.parametrize(
    "text,expected",
    [("3", False), ("1 实验", False), ("N%", True), ("1.4 V", True), ("9.9 mA", True)],
)
def test_retry_targets_measurements_not_page_or_section_numbers(text, expected):
    from aletheia_nexus.content.backends.tesseract import _retry_candidate

    assert (
        _retry_candidate(
            LayoutLine(text, 20, 200, 100, 220, 12, extraction_confidence=0.62)
        )
        == expected
    )


def test_separate_numeric_cells_are_not_merged_into_one_number():
    from aletheia_nexus.content.backends.adaptive import _similar

    assert not _similar("1 2", "12", 0.82)
    assert not _similar("1.5 2", "1.52", 0.82)
    assert _similar("12 mA", "12mA", 0.82)


@pytest.mark.parametrize(
    "first,second,promote",
    [("9.4", "99.4", True), ("99.4", "99.5", False)],
)
def test_missing_native_glyph_count_can_rank_complete_ocr_readings(
    first, second, promote
):
    native = StaticBackend("The material purity was \x00\x00.\x00% after washing.")
    backend = AdaptiveOcrBackend(
        native_backend=native,
        ocr_backends=(
            StaticBackend(f"The material purity was {first}% after washing.", 0.96),
            StaticBackend(f"The material purity was {second}% after washing.", 0.84),
        ),
    )
    result = backend.extract_page(None, 1)
    expected = second if promote else first
    assert result.lines[0].text == f"The material purity was {expected}% after washing."
    assert result.lines[0].uncertain
    assert any(f"{first}%" in line.text for line in result.lines)
    assert any(f"{second}%" in line.text for line in result.lines)


def test_damaged_glyph_fit_does_not_guess_values_or_change_known_units():
    from aletheia_nexus.content.backends.adaptive import _fits_damaged_native

    assert not _fits_damaged_native("\x00\x00.\x00%", "99.4%")
    assert not _fits_damaged_native(
        "Measured current is \x00\x00 mA.", "Measured current is 12 MA."
    )
    assert not _fits_damaged_native(
        "Measured current is \x00\x00 mA.", "Measured current is \x00\x00 mA."
    )


def test_duplicate_conflicts_keep_one_reading_with_both_engine_sources():
    from dataclasses import replace

    native = StaticBackend("yield 13%").extract_page(None, 1)
    a = StaticBackend("yield 18%", 0.95).extract_page(None, 1)
    b = replace(a, lines=(replace(a.lines[0], source_engines=("second-ocr",)),))
    lines, warnings = AdaptiveOcrBackend()._merge(native, [a, b])
    assert len(lines) == 2 and all(line.uncertain for line in lines)
    assert "second-ocr" in lines[1].source_engines
    assert len(lines[1].source_engines) == 2
    assert sum(w["code"] == "OCR_ENGINE_DISAGREEMENT" for w in warnings) == 1
    distant = replace(b, lines=(replace(b.lines[0], y0=600, y1=620),))
    lines, _ = AdaptiveOcrBackend()._merge(native, [a, distant])
    assert len(lines) == 3


@pytest.mark.parametrize("mapped", [False, True])
def test_partial_unicode_cff_font_recovers_only_unmapped_strokes(mapped):
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.t2CharStringPen import T2CharStringPen

    builder = FontBuilder(1000, isTTF=False)
    builder.setupGlyphOrder([".notdef", "unknownShape"])
    empty = T2CharStringPen(400, None)
    stroke = T2CharStringPen(400, None)
    stroke.moveTo((60, 210))
    stroke.lineTo((350, 210))
    stroke.lineTo((350, 276))
    stroke.lineTo((60, 276))
    stroke.closePath()
    builder.setupCFF(
        "SelfAuthoredCff",
        {"FullName": "SelfAuthoredCff"},
        {".notdef": empty.getCharString(), "unknownShape": stroke.getCharString()},
        {},
    )
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    stream = DecodedStreamObject()
    stream.set_data(builder.font["CFF "].compile(builder.font))
    stream[NameObject("/Subtype")] = NameObject("/Type1C")
    cmap = DecodedStreamObject()
    code = b"<02> <0040>" if mapped else b"<20> <0020>"
    cmap.set_data(
        b"begincmap 1 begincodespacerange <00> <ff> endcodespacerange 1 beginbfchar "
        + code
        + b" endbfchar endcmap"
    )
    definition = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/SelfAuthoredCff"),
            NameObject("/FirstChar"): NumberObject(2),
            NameObject("/LastChar"): NumberObject(2),
            NameObject("/Widths"): ArrayObject([NumberObject(400)]),
            NameObject("/Encoding"): DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Encoding"),
                    NameObject("/Differences"): ArrayObject(
                        [NumberObject(2), NameObject("/unknownShape")]
                    ),
                }
            ),
            NameObject("/ToUnicode"): cmap,
            NameObject("/FontDescriptor"): DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/FontDescriptor"),
                    NameObject("/FontName"): NameObject("/SelfAuthoredCff"),
                    NameObject("/Flags"): NumberObject(4),
                    NameObject("/FontBBox"): ArrayObject(
                        [NumberObject(x) for x in [0, 0, 400, 800]]
                    ),
                    NameObject("/Ascent"): NumberObject(800),
                    NameObject("/Descent"): NumberObject(0),
                    NameObject("/FontFile3"): writer._add_object(stream),
                }
            ),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): definition})}
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 50 700 Td <02> Tj ET")
    page[NameObject("/Contents")] = content
    result = LayoutPdfBackend().extract_page(page, 1)
    assert result.lines[0].text == ("@" if mapped else "-")
