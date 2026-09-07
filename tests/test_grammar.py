# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from kolint import Segment, lint_text, run
from kolint.engine import build_rules, fix
from kolint.rules.grammar import correct_josa


def codes(target, source=None, select=None):
    return sorted(d.code for d in lint_text(target, source, select=select))


# --- KO001 duplicate particle -----------------------------------------------

@pytest.mark.parametrize(
    "bad,good",
    [
        ("그를을 보았다.", "그를 보았다."),
        ("나는은 간다.", "나는 간다."),
        ("이것은는 아니다.", "이것은 아니다."),
    ],
)
def test_duplicate_particle(bad, good):
    diags = [d for d in lint_text(bad) if d.code == "KO001"]
    assert diags, bad
    assert diags[0].fix == good


@pytest.mark.parametrize(
    "text",
    [
        "예전에는 치과와 외과를 해봤어.",   # 치과 + 와 ("and")
        "사과와 시체를 저장하는 곳이야.",   # 사과 + 와
        "그 물약의 효과와 맞지 않는다.",  # 효과 + 와
        "결과와 원인을 혼동하지 마라.",     # 결과 + 와
    ],
)
def test_duplicate_particle_excludes_gwa_wa(text):
    """과와 is noun + 와, not a doubled particle. All four are real corpus lines."""
    assert "KO001" not in codes(text), text


# --- KO004 redundant copula (opt-in) ----------------------------------------

@pytest.mark.parametrize(
    "bad,good",
    [
        ("그것은 검이입니다.", "그것은 검입니다."),
        ("이건 문제이이다.", "이건 문제이다."),
        ("저는 성직자이이에요.", "저는 성직자이에요."),
        ("그거 진짜이이야.", "그거 진짜이야."),
    ],
)
def test_redundant_copula(bad, good):
    diags = [d for d in lint_text(bad, select=["KO004"]) if d.code == "KO004"]
    assert diags, bad
    assert diags[0].fix == good


def test_redundant_copula_is_opt_in():
    assert "KO004" not in codes("그것은 검이입니다.")


@pytest.mark.parametrize(
    "text",
    [
        "그 시간대의 길이입니다.",   # 길이 = length
        "그건 고양이이다.",           # 고양이 = cat
        "제 나이입니다.",             # 나이 = age
        "이건 종이입니다.",           # 종이 = paper
        "저건 아이이다.",             # 아이 = child
    ],
)
def test_redundant_copula_skips_i_final_nouns(text):
    """이입니다 is correct when the preceding word is itself an 이-final noun."""
    assert "KO004" not in codes(text, select=["KO004"]), text


def test_no_false_positive_on_iga_like_words():
    # 고양이가 / 아이가 are noun + subject particle, not a duplicated particle.
    for text in ("고양이가 운다.", "아이가 웃는다.", "종이가 찢어졌다."):
        assert "KO001" not in codes(text), text


# --- KO002 past tense + 는다 -------------------------------------------------

@pytest.mark.parametrize(
    "bad,good",
    [
        ("그는 문을 열었는다.", "그는 문을 열었다."),
        ("비가 왔는다.", "비가 왔다."),
        ("그것은 사실이었는다.", "그것은 사실이었다."),
        ("일이 그렇게 됐는다.", "일이 그렇게 됐다."),
    ],
)
def test_past_neunda(bad, good):
    diags = [d for d in lint_text(bad) if d.code == "KO002"]
    assert diags, bad
    assert diags[0].fix == good


def test_past_neunda_leaves_valid_present_alone():
    for text in ("그는 밥을 먹는다.", "물이 흘른다.", "그가 문을 연다."):
        assert "KO002" not in codes(text), text


# --- KO003 adjective + 는다 --------------------------------------------------

@pytest.mark.parametrize(
    "bad,good",
    [
        ("날씨가 좋는다.", "날씨가 좋다."),
        ("돈이 없는다.", "돈이 없다."),
        ("그건 중요한다.", "그건 중요하다."),
        ("정말 위험한다.", "정말 위험하다."),
    ],
)
def test_adjective_neunda(bad, good):
    diags = [d for d in lint_text(bad) if d.code == "KO003"]
    assert diags, bad
    assert diags[0].fix == good


def test_adjective_rule_excludes_verb_homographs():
    # 적다 "write down" and 밝다 "dawn breaks" have valid -는다 forms.
    assert "KO003" not in codes("그는 수첩에 적는다.")
    assert "KO003" not in codes("날이 밝는다.")


# --- KO005 placeholder + josa ------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "{name}을 만났다.",
        "{0}이 도착했습니다.",
        "%s를 획득했다.",
        "${player}는 준비됐다.",
        "<<item>>과 교환한다.",
        "[PLAYER]가 입장했습니다.",
    ],
)
def test_placeholder_josa_flagged(text):
    assert "KO005" in codes(text), text


@pytest.mark.parametrize(
    "text",
    [
        "{name}을(를) 만났다.",
        "{name}에게 말했다.",
        "{count}개를 획득했다.",
        "{name} 님이 도착했습니다.",
    ],
)
def test_placeholder_josa_safe_forms(text):
    assert "KO005" not in codes(text), text


# --- KO006 glossary josa -----------------------------------------------------

def test_glossary_josa_requires_config():
    assert "KO006" not in codes("성직자을 만났다.")


def test_glossary_josa_with_config():
    from kolint.config import Config

    cfg = Config(rules={"KO006": {"terms": ["성직자", "코볼드", "은빛 탑"]}})
    rules = build_rules(cfg, select=["KO006"])
    segs = [Segment(target="성직자을 만났다.")]
    diags = run(segs, rules)
    assert [d.code for d in diags] == ["KO006"]
    assert diags[0].fix == "성직자를 만났다."

    # And the correct form is silent.
    assert not run([Segment(target="성직자를 만났다.")], rules)
    assert not run([Segment(target="코볼드가 나타났다.")], rules)
    assert run([Segment(target="코볼드이 나타났다.")], rules)


# --- KO007 heuristic josa ----------------------------------------------------

def test_josa_agreement_is_opt_in():
    assert "KO007" not in codes("사과을 먹었다.")
    assert "KO007" in codes("사과을 먹었다.", select=["KO007"])


def test_josa_agreement_stopwords():
    # 가을 is a noun, not 가 + 을.
    assert "KO007" not in codes("가을 하늘이 높다.", select=["KO007"])


# --- correct_josa ------------------------------------------------------------

@pytest.mark.parametrize(
    "word,josa,expected",
    [
        ("성직자", "을", "를"),
        ("코볼드", "이", "가"),   # 드 has no batchim
        ("물", "가", "이"),
        ("나", "은", "는"),
        ("책", "를", "을"),
        ("서울", "으로", "로"),   # ㄹ batchim takes the vowel form
        ("부산", "로", "으로"),
        ("칼", "과", "과"),
    ],
)
def test_correct_josa(word, josa, expected):
    assert correct_josa(word, josa) == expected


def test_correct_josa_unknown_for_latin():
    assert correct_josa("HP", "을") is None


# --- fix loop composes -------------------------------------------------------

def test_multiple_rules_compose_in_fix():
    seg = Segment(target="그것은 사실이입니다. 날씨가 좋는다.")
    rules = build_rules(select=["KO003", "KO004"])
    n = fix([seg], rules)
    assert n == 2
    assert seg.target == "그것은 사실입니다. 날씨가 좋다."
