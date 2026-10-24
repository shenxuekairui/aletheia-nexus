"""An embedded ligature may have different bounds on the same text baseline."""

from test_nested_scripts import glyph

from aletheia_nexus.content.backends.layout import _attach_inline_glyphs


def test_isolated_ligature_and_unreadable_glyph_rejoin_only_their_painted_word():
    left, right = glyph("i", 10, 40, 10), glyph("u", 19, 40, 10)
    ligature = glyph("ﬀ", 13, 44, 10, width=6, origin=40)
    pua = glyph("\ue104", 113, 44, 10, width=6, origin=40)
    row = [left, right, glyph("a", 110, 40, 10), glyph("o", 119, 40, 10)]
    rows = [row, [ligature, pua]]
    assert not _attach_inline_glyphs(rows)
    assert sorted(c.get_text() for c in row) == sorted(
        ["i", "u", "a", "o", "ﬀ", "\ue104"]
    )
    assert rows[1] == []
    assert ligature.y0 == 44 and pua.get_text() == "\ue104"


def test_different_baseline_separate_measurement_and_one_sided_label_stay_put():
    for source in (
        glyph("x", 13, 44, 10),
        glyph("7", 13, 40, 10),
        glyph("V", 22, 40, 10),
    ):
        row = [glyph("a", 10, 40, 10), glyph("b", 19, 40, 10)]
        rows = [row, [source]]
        assert not _attach_inline_glyphs(rows)
        assert rows[1] == [source]


def test_competing_word_rows_abstain_and_flag_the_original_glyph():
    source = glyph("ﬂ", 13, 44, 10, width=6, origin=40)
    rows = [[glyph("a", 10, 40, 10), glyph("b", 19, 40, 10)] for _ in range(2)]
    rows.append([source])
    assert _attach_inline_glyphs(rows) == {id(source)}
    assert rows[-1] == [source]


def test_already_connected_native_word_cannot_be_reassigned():
    source = glyph("ﬂ", 13, 44, 10, width=6, origin=40)
    own = [glyph("a", 10, 40, 10), source]
    target = [glyph("b", 10, 40, 10), glyph("c", 19, 40, 10)]
    rows = [own, target]
    assert not _attach_inline_glyphs(rows)
    assert source in own and source not in target
