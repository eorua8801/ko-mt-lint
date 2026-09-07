# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from kolint import Segment, lint_text, run
from kolint.engine import build_rules


def codes(target, source=None):
    return sorted(d.code for d in lint_text(target, source))


# --- KO401 fronted pronoun ---------------------------------------------------

def test_fronted_pronoun_in_narration():
    diags = [
        d
        for d in lint_text("당신은 문 앞에 서 있다.", "You stand before the door.")
        if d.code == "KO401"
    ]
    assert diags
    assert diags[0].fix == "문 앞에 서 있다."


def test_fronted_pronoun_skips_dialogue():
    assert "KO401" not in codes('"당신은 누구죠?"', '"Who are you?"')


def test_fronted_pronoun_only_at_the_front():
    assert "KO401" not in codes("문 앞에 선 당신은 망설인다.", "You hesitate.")


def test_fronted_pronoun_is_info_severity():
    diags = [d for d in lint_text("당신은 걷는다.", "You walk.") if d.code == "KO401"]
    assert diags[0].severity == "info"


# --- KO402 double passive ----------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "그것은 잘 보여진다.",
        "일이 되어졌다.",
        "그 이름으로 불려진다.",
        "책에 쓰여져 있다.",
        "이미 잊혀진 이야기.",
        "문이 닫혀졌다.",
    ],
)
def test_double_passive_detected(text):
    assert "KO402" in codes(text), text


@pytest.mark.parametrize(
    "text",
    [
        "이 도구는 나무로 만들어졌다.",   # 만들다 -> 만들어지다, standard
        "합의가 이루어졌다.",             # 이루다 -> 이루어지다, standard
        "그 사실은 널리 알려졌다.",        # 알려지다, standard
        "진실이 밝혀졌다.",               # 밝혀지다, standard
        "가려진 얼굴.",                   # 가리다 -> 가려지다, standard
    ],
)
def test_double_passive_leaves_standard_passives_alone(text):
    assert "KO402" not in codes(text), text


def test_double_passive_has_no_autofix():
    diags = [d for d in lint_text("그것은 보여진다.") if d.code == "KO402"]
    assert diags and diags[0].fix is None


# --- KO403 typography --------------------------------------------------------

def test_space_before_punctuation():
    diags = [d for d in lint_text("안녕하세요 .", "Hello.") if d.code == "KO403"]
    assert diags and diags[0].fix == "안녕하세요."


def test_missing_space_after_comma():
    diags = [d for d in lint_text("안녕,반가워요.", "Hi, nice to meet you.") if d.code == "KO403"]
    assert diags and diags[0].fix == "안녕, 반가워요."


def test_double_space():
    diags = [d for d in lint_text("안녕  하세요.", "Hello.") if d.code == "KO403"]
    assert diags and diags[0].fix == "안녕 하세요."


def test_typography_respects_the_source():
    # The source has the same double space, so it was authored deliberately.
    assert "KO403" not in codes("안녕  하세요.", "Hello  there.")


def test_ellipsis_is_not_flagged():
    assert "KO403" not in codes("글쎄... 모르겠는데.", "Well... I don't know.")


def test_thousands_separator_is_not_flagged():
    assert "KO403" not in codes("금화 1,000닢", "1,000 gold")


def test_trailing_whitespace():
    diags = [d for d in lint_text("안녕하세요. ", "Hello.") if d.code == "KO403"]
    assert diags


def test_trailing_whitespace_allowed_when_source_has_it():
    assert "KO403" not in codes("안녕하세요. ", "Hello. ")


# --- fix loop ----------------------------------------------------------------

def test_style_and_grammar_fixes_compose():
    from kolint.engine import fix

    seg = Segment(
        target="당신은 문 앞에 서 있는다 .",
        source="You stand before the door.",
    )
    n = fix([seg], build_rules(select=["KO002", "KO401", "KO403"]))
    assert n == 3
    assert seg.target == "문 앞에 서 있다."


def test_fronted_pronoun_fix_cascades():
    """Stripping one fronted pronoun can expose another; both go.

    ``당신은 그것이 ...`` is doubly marked in a language that drops subjects,
    so removing only the outer one would leave the sentence still reading as
    a translation.
    """
    from kolint.engine import fix

    seg = Segment(target="당신은 그것이 사실임을 안다.", source="You know it is true.")
    fix([seg], build_rules(select=["KO401"]))
    assert seg.target == "사실임을 안다."
