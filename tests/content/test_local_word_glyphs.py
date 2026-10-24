"""Local OCR can fill explicit letter gaps without copying its other errors."""

from dataclasses import replace

import pytest

from aletheia_nexus.content.backends import AdaptiveOcrBackend
from aletheia_nexus.content.models import LayoutLine, PageLayout


def native_line(text="A Pt/C (23 wt%) layer on the coef\ue123cient membrane at 25 °C"):
    return LayoutLine(
        text,
        30,
        200,
        530,
        212,
        10,
        uncertain=True,
        source_engines=("native",),
        glyph_spans=tuple((i, i + 1, 30 + i * 8, 38 + i * 8) for i in range(len(text))),
    )


def merge(native, text, **kw):
    page = PageLayout(page=2, width=600, height=800, lines=(native,))
    ocr = replace(
        native,
        text=text,
        extraction_method="ocr",
        source_engines=("ocr",),
        glyph_spans=(),
        extraction_confidence=0.96,
        **kw,
    )
    return AdaptiveOcrBackend()._merge(page, [replace(page, lines=(ocr,))])


def test_missing_ligature_only_uses_observed_word_and_preserves_native_scientific_text():
    source = native_line()
    ocr = "A PUC (23 wi%) layer on the coefficient membrane at 25 °C"
    output, warnings = merge(source, ocr)
    assert output[0].text == source.text.replace("\ue123", "fi")
    assert output[0].uncertain
    assert {x.text for x in output[1:]} == {source.text, ocr}
    assert all(x.content_region.endswith("alternative") for x in output[1:])
    warning = next(w for w in warnings if w["code"] == "OCR_GLYPH_WORD_RECOVERED")
    assert warning["after"] == "fi" and warning["page"] == 2
    assert warning["bbox"][1:4:2] == pytest.approx([200 / 800, 212 / 800])


@pytest.mark.parametrize(
    "text",
    [
        "A Pt/C (23 wt%) layer on the COEFFICIENT membrane at 25 °C",
        "A Pt/C (23 wt%) layer on the coefficient membrane at 28 °C",
        "A Pt/C (23 wt%) layer on the coefficient coefficient membrane at 25 °C",
        "A different experiment uses coefficient with changed conditions 25 °C",
    ],
)
def test_case_numbers_repeated_words_or_different_context_do_not_repair(text):
    source = native_line()
    output, _ = merge(source, text)
    assert output[0].text == source.text


def test_missing_position_low_confidence_and_distant_ocr_do_not_repair():
    source = native_line()
    text = source.text.replace("\ue123", "fi")
    for native, kw in [
        (replace(source, glyph_spans=()), {}),
        (source, dict(x0=350, x1=580)),
        (source, dict(y0=300, y1=312)),
    ]:
        output, _ = merge(native, text, **kw)
        assert output[0].text == source.text
    page = PageLayout(page=2, width=600, height=800, lines=(source,))
    low = replace(
        source,
        text=text,
        extraction_confidence=0.89,
        source_engines=("ocr",),
        glyph_spans=(),
    )
    output, _ = AdaptiveOcrBackend()._merge(page, [replace(page, lines=(low,))])
    assert output[0].text == source.text


def test_numeric_gap_and_unmarked_spelling_are_never_filled():
    for text in (
        "A measured 2\ue1233 mV under the reported conditions",
        "The coeficient membrane was measured at 25 °C",
    ):
        source = native_line(text)
        output, _ = merge(
            source, text.replace("\ue123", "8").replace("coeficient", "coefficient")
        )
        assert output[0].text == text
