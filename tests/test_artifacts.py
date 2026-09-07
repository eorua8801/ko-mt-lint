# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from kolint import Segment, lint_text, run
from kolint.engine import build_rules


def codes(target, source=None, select=None):
    return sorted(d.code for d in lint_text(target, source, select=select))


# --- KO101 thinking residue --------------------------------------------------

@pytest.mark.parametrize(
    "bad",
    [
        "마지막으로 /think",
        "<think>어떻게 번역할까</think>안녕하세요",
        "안녕하세요 /no_think",
        "반갑습니다<|im_end|>",
    ],
)
def test_thinking_residue(bad):
    assert "KO101" in codes(bad), bad


def test_thinking_residue_fix_strips_marker():
    diags = [d for d in lint_text("마지막으로 /think") if d.code == "KO101"]
    assert diags[0].fix.strip() == "마지막으로"


# --- KO102 script leak -------------------------------------------------------

def test_script_leak_against_source():
    diags = [d for d in lint_text("그는 战栗했다.", "He shuddered.") if d.code == "KO102"]
    assert diags
    assert "한자" in diags[0].message


def test_script_leak_allows_scripts_present_in_source():
    assert "KO102" not in codes("도쿄(東京)로 갔다.", "He went to Tokyo (東京).")


def test_script_leak_flags_kana():
    assert "KO102" in codes("그는 ありがとう라고 말했다.", "He said thanks.")


def test_script_leak_clean_korean_is_silent():
    assert "KO102" not in codes("그는 몸을 떨었다.", "He shuddered.")


# --- KO103 untranslated ------------------------------------------------------

def test_untranslated_passthrough():
    src = "The pale man sits hunched over a stack of forms."
    diags = [d for d in lint_text(src, src) if d.code == "KO103"]
    assert diags and diags[0].severity == "error"


def test_untranslated_ignores_short_symbolic_strings():
    assert "KO103" not in codes("HP", "HP")
    assert "KO103" not in codes("OK", "OK")


def test_untranslated_ignores_mixed_korean():
    assert "KO103" not in codes("HP를 회복한다", "Restore HP")


# --- KO104 meta commentary ---------------------------------------------------

@pytest.mark.parametrize(
    "bad,clean",
    [
        ("번역: 안녕하세요.", "안녕하세요."),
        ("Translation: 안녕하세요.", "안녕하세요."),
        ("Here is the Korean translation: 안녕하세요.", "안녕하세요."),
        ("```\n안녕하세요.", "안녕하세요."),
    ],
)
def test_meta_commentary(bad, clean):
    diags = [d for d in lint_text(bad) if d.code == "KO104"]
    assert diags, bad
    assert diags[0].fix == clean


def test_meta_commentary_does_not_eat_real_text():
    assert "KO104" not in codes("번역가는 지쳐 있었다.")


# --- KO105 repetition --------------------------------------------------------

def test_repetition_tokens():
    assert "KO105" in codes("그는 그는 그는 걸었다.")


def test_repetition_chars():
    assert "KO105" in codes("으아아아아아아악")


def test_repetition_leaves_normal_text():
    assert "KO105" not in codes("하하하 재미있군.")
    assert "KO105" not in codes("그는 천천히 걸었다.")


# --- integration -------------------------------------------------------------

def test_group_scoped_rules_do_not_crash_without_group():
    rules = build_rules(select=["all"])
    segs = [Segment(target="안녕하세요."), Segment(target="반갑습니다.")]
    run(segs, rules)  # must not raise
