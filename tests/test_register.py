# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from kolint import Segment, run
from kolint.config import Config
from kolint.engine import build_rules
from kolint.rules.register import detect_level, line_kind


# --- level detection ---------------------------------------------------------

@pytest.mark.parametrize(
    "text,level",
    [
        ("저는 성직자입니다.", "formal"),
        ("어디로 가십니까?", "formal"),
        ("이쪽으로 오십시오.", "formal"),
        ("저도 그렇게 생각해요.", "polite"),
        ("맞죠?", "polite"),
        ("그는 문을 열었다.", "plain"),
        ("비가 온다.", "plain"),
        ("나도 갈래.", "casual"),
        ("빨리 와!", "casual"),
        ("그거 진짜야?", "casual"),
        ("나 벌써 갔어", "casual"),      # ㅆ + 어 needs no punctuation
        ("너도 알잖아", "casual"),        # unambiguous multi-syllable ending
    ],
)
def test_detect_level(text, level):
    assert detect_level(text) == level


def test_detect_level_returns_none_for_fragments():
    assert detect_level("성직자") is None
    assert detect_level("HP") is None
    assert detect_level("") is None


@pytest.mark.parametrize("noun", ["성직자", "노래", "동네", "분야", "이해", "편지"])
def test_ambiguous_endings_need_sentence_punctuation(noun):
    # These noun finals are homographic with 해체 endings; without terminal
    # punctuation they must not be counted as a speech level.
    assert detect_level(noun) is None
    assert detect_level("그 " + noun) is None


def test_detect_level_uses_last_sentence():
    assert detect_level("그는 걸었다. 정말 좋았어요.") == "polite"


def test_detect_level_ignores_trailing_quotes():
    assert detect_level('"저는 성직자입니다."') == "formal"


# --- line kinds --------------------------------------------------------------

def test_line_kind():
    assert line_kind(Segment(target="x", source='"Hello."')) == "dialogue"
    assert line_kind(Segment(target="x", source="(Look around.)")) == "choice"
    assert line_kind(Segment(target="x", source="The man sits.")) == "narration"
    # Falls back to the target when no source is present.
    assert line_kind(Segment(target='"안녕."')) == "dialogue"


# --- KO301 drift -------------------------------------------------------------

def _dialogue(group, lines):
    return [Segment(target='"%s"' % t, source='"x"', group=group) for t in lines]


def test_register_drift_flags_the_minority():
    segs = _dialogue(
        "Archivist",
        [
            "저는 성직자입니다.",
            "그렇게 하겠습니다.",
            "잠시만 기다리십시오.",
            "여기 있습니다.",
            "알겠습니다.",
            "나도 그래.",         # <- the odd one out
        ],
    )
    diags = [d for d in run(segs, build_rules(select=["KO301"]))]
    assert len(diags) == 1
    assert diags[0].segment.target == '"나도 그래."'


def test_register_drift_stays_quiet_on_genuinely_mixed_groups():
    segs = _dialogue(
        "Mixed",
        ["저는 갑니다.", "나도 가.", "그래요.", "간다.", "가십시오.", "먹었어."],
    )
    assert not run(segs, build_rules(select=["KO301"]))


def test_register_drift_needs_enough_evidence():
    segs = _dialogue("Tiny", ["갑니다.", "가."])
    assert not run(segs, build_rules(select=["KO301"]))


def test_register_drift_separates_narration_from_dialogue():
    segs = [
        Segment(target="그는 문을 열었다.", source="He opened the door.", group="Scene"),
        Segment(target="그는 앉았다.", source="He sat.", group="Scene"),
        Segment(target="그는 웃었다.", source="He smiled.", group="Scene"),
        Segment(target="바람이 불었다.", source="Wind blew.", group="Scene"),
        Segment(target="문이 닫혔다.", source="The door shut.", group="Scene"),
        Segment(target='"안녕하세요."', source='"Hello."', group="Scene"),
        Segment(target='"반갑습니다."', source='"Nice to meet you."', group="Scene"),
    ]
    # Narration is 다체 throughout and dialogue is 합니다체 -- both internally
    # consistent, so nothing is reported.
    assert not run(segs, build_rules(select=["KO301"]))


# --- KO302 speaker profiles --------------------------------------------------

def _rules_with_speakers(mapping):
    return build_rules(Config(rules={"KO302": {"speakers": mapping}}), select=["KO302"])


def test_speaker_register_violation():
    rules = _rules_with_speakers({"Archivist": "formal"})
    segs = [
        Segment(target='"저는 성직자입니다."', source='"x"', group="NPC_Archivist"),
        Segment(target='"나도 그래."', source='"y"', group="NPC_Archivist"),
    ]
    diags = run(segs, rules)
    assert len(diags) == 1
    assert "합니다체" in diags[0].message and "반말" in diags[0].message


def test_speaker_name_matches_story_prefixes():
    rules = _rules_with_speakers({"Scout": "casual"})
    for group in ("Scout_Companion", "EP_Scout", "JC_Scout"):
        segs = [Segment(target='"안녕하십니까."', source='"x"', group=group)]
        assert run(segs, rules), group


def test_speaker_register_ignores_unknown_groups():
    rules = _rules_with_speakers({"Archivist": "formal"})
    segs = [Segment(target='"나도 그래."', source='"x"', group="Someone_Else")]
    assert not run(segs, rules)


def test_speaker_register_rejects_bad_level():
    with pytest.raises(ValueError):
        _rules_with_speakers({"Archivist": "존댓말"})


def test_speaker_register_is_silent_without_config():
    segs = [Segment(target='"나도 그래."', source='"x"', group="NPC_Archivist")]
    assert not run(segs, build_rules(select=["KO302"]))
