# -*- coding: utf-8 -*-
"""Regressions for false positives found by running against a real corpus.

Every case here was produced by a first version of the rule that looked
correct in isolation and was wrong on 70k lines of shipped game dialogue.
"""

from __future__ import annotations

import pytest

from kolint import Segment, lint_text, run
from kolint.engine import build_rules
from kolint.rules.register import level_of


def codes(target, source=None, select=None):
    return sorted(d.code for d in lint_text(target, source, select=select))


# --- KO004: 이입니다 after an 이-final noun is correct Korean ------------------

def test_length_is_not_a_doubled_copula():
    # "...결정하는 것은 그 시간대의 길이입니다." -- 길이 means "length".
    # A naive 이입니다 -> 입니다 rewrite produced "길입니다", destroying it.
    text = "결정하는 것은 그 시간대의 길이입니다."
    assert "KO004" not in codes(text, select=["KO004"])


# --- KO103: control strings are meant to pass through -------------------------

@pytest.mark.parametrize(
    "text",
    [
        "SPELL Inflict_Wounds-",
        "SPELL Charm_Person-",
        "SPELL Comprehend_Languages-",
        "ITEM_KEY_RUSTY",
    ],
)
def test_identifier_strings_are_not_untranslated_bugs(text):
    assert "KO103" not in codes(text, text)


def test_real_untranslated_prose_still_reported():
    src = "The pale man sits hunched over a stack of forms."
    assert "KO103" in codes(src, src)


def test_untranslated_ignore_pattern_is_configurable():
    from kolint.config import Config

    cfg = Config(rules={"KO103": {"ignore_pattern": r"^\[NOLOC\]"}})
    rules = build_rules(cfg, select=["KO103"])
    seg = Segment(target="[NOLOC] Some English text here", source="[NOLOC] Some English text here")
    assert not run([seg], rules)


# --- KO105: stylised repetition exists in the source too ----------------------

@pytest.mark.parametrize(
    "source,target",
    [
        ("<b>YEEEEEEEEEEEEEES</b>.", "<b>YEEEEEEEEEEEEEES</b>."),
        ("<shake>RHOOOOOOOOAAAAH...!</shake>", "<shake>RHOOOOOOOOAAAAH...!</shake>"),
        ("Death. Death. Death.", "사망. 사망. 사망."),
        ("Try... Try... Try...", "시도해보세요... 시도해보세요... 시도해보세요..."),
        ("NOOOOOOOO.", "아니이이이이이이이이."),
    ],
)
def test_repetition_present_in_source_is_intentional(source, target):
    assert "KO105" not in codes(target, source), target


def test_repetition_without_source_support_is_still_reported():
    assert "KO105" in codes("아니이이이이이이이이.", "No.")
    assert "KO105" in codes("그는 그는 그는 걸었다.", "He walked.")


# --- KO301: narration that quotes dialogue --------------------------------

def test_narration_level_ignores_quoted_dialogue():
    # The narration is 다체 ("말한다"); the quote at the end is the
    # character's 반말 and must not be attributed to the narrator.
    seg = Segment(
        target='그녀가 뒤를 돌아보며 말한다. "고블린들은 완벽하지 않지만, 좋은 점을 알아야 해."',
        source='She looks behind her. "The goblins are not perfect."',
    )
    assert level_of(seg) == "plain"


def test_dialogue_level_still_reads_the_quote():
    seg = Segment(target='"고블린들은 좋은 점이 있어."', source='"They have good in them."')
    assert level_of(seg) == "casual"


def test_narration_drift_not_reported_for_embedded_quotes():
    narration = [
        Segment(target="그는 문을 열었다.", source="He opened the door.", group="S"),
        Segment(target="그는 앉았다.", source="He sat down.", group="S"),
        Segment(target="바람이 불었다.", source="Wind blew.", group="S"),
        Segment(target="문이 닫혔다.", source="The door shut.", group="S"),
        Segment(target="불빛이 흔들린다.", source="The light flickers.", group="S"),
        Segment(
            target='그녀가 말한다. "빨리 와!"',
            source='She says, "Come quick!"',
            group="S",
        ),
    ]
    assert not run(narration, build_rules(select=["KO301"]))


def test_genuine_narration_drift_is_still_reported():
    narration = [
        Segment(target="그는 문을 열었다.", source="He opened the door.", group="S"),
        Segment(target="그는 앉았다.", source="He sat down.", group="S"),
        Segment(target="바람이 불었다.", source="Wind blew.", group="S"),
        Segment(target="문이 닫혔다.", source="The door shut.", group="S"),
        Segment(target="불빛이 흔들린다.", source="The light flickers.", group="S"),
        Segment(target="약간의 농담은 문제 없어.", source="No harm in teasing.", group="S"),
    ]
    diags = run(narration, build_rules(select=["KO301"]))
    assert len(diags) == 1
    assert diags[0].segment.target == "약간의 농담은 문제 없어."


# --- KO004: the dependent noun 이 ("the one who ...") -------------------------

def test_dependent_noun_i_is_not_a_doubled_copula():
    # "...생활 방식을 만든 이이다." -- 이 here is the bound noun "one/person",
    # so 이 + 이다 is correct and collapsing it to "만든 이다" is wrong.
    text = "아스카니의 생활 방식을 만든 이이다."
    assert "KO004" not in codes(text, select=["KO004"])


# --- KO301: dialogue with a trailing speech tag ------------------------------

def test_dialogue_level_ignores_trailing_speech_tag():
    # The speaker is 해요체; "말한다" belongs to the narrator, not to her.
    seg = Segment(
        target='"아니요, 그러지 않았어요," 주술사가 냉소하며 말한다.',
        source='"No, I did not," the hag sneers.',
    )
    assert level_of(seg, "dialogue") == "polite"
