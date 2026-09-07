# -*- coding: utf-8 -*-
from __future__ import annotations

from kolint import lint_text


def codes(target, source=None):
    return sorted(d.code for d in lint_text(target, source))


# --- KO201 tags --------------------------------------------------------------

def test_missing_tag():
    diags = [
        d for d in lint_text("그 강이 아니에요.", "Not <i>a</i> river.") if d.code == "KO201"
    ]
    assert diags
    assert "누락" in diags[0].message


def test_extra_tag():
    diags = [d for d in lint_text("<b>강</b>", "river") if d.code == "KO201"]
    assert diags and "추가" in diags[0].message


def test_matching_tags_are_silent():
    assert "KO201" not in codes("<i>그</i> 강이에요.", "<i>The</i> river.")


def test_unity_rich_text_tags():
    assert "KO201" in codes("붉은 글씨", '<color=#ff0000>red text</color>')
    assert "KO201" not in codes(
        "<color=#ff0000>붉은 글씨</color>", '<color=#ff0000>red text</color>'
    )


def test_tag_order_mismatch():
    diags = [
        d
        for d in lint_text("<b><i>강</i></b>", "<i><b>river</b></i>")
        if d.code == "KO201"
    ]
    assert diags and "순서" in diags[0].message


# --- KO202 placeholders ------------------------------------------------------

def test_missing_placeholder():
    diags = [d for d in lint_text("아이템을 얻었다.", "You got {item}.") if d.code == "KO202"]
    assert diags and "누락" in diags[0].message


def test_invented_placeholder():
    diags = [d for d in lint_text("{item}을 얻었다.", "You got it.") if d.code == "KO202"]
    assert diags and "없는" in diags[0].message


def test_placeholder_counts_matter():
    assert "KO202" in codes("{a} {a}", "{a}")
    assert "KO202" not in codes("{a}와 {b}", "{a} and {b}")


def test_printf_placeholders():
    assert "KO202" in codes("%d개 획득", "You got %d %s.")
    assert "KO202" not in codes("%s를 %d개 얻었다", "Got %d of %s")


# --- KO203 line breaks -------------------------------------------------------

def test_linebreak_mismatch():
    assert "KO203" in codes("한 줄로 합쳤다", "two\nlines")
    assert "KO203" not in codes("두\n줄", "two\nlines")


def test_literal_backslash_n_counted_separately():
    assert "KO203" not in codes("두\\n줄", "two\\nlines")
    assert "KO203" in codes("한 줄", "two\\nlines")


def test_br_tags():
    assert "KO203" in codes("한 줄", "two<br>lines")


# --- no source, no markup diagnostics ---------------------------------------

def test_markup_rules_need_a_source():
    assert "KO201" not in codes("<i>강</i>")
    assert "KO202" not in codes("{item}")
    assert "KO203" not in codes("두\n줄")
