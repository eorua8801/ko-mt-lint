"""Hangul syllable primitives.

Everything here is pure arithmetic on Unicode code points -- no tables, no
dependencies. Korean syllables live in a contiguous block where

    code = 0xAC00 + (cho * 21 + jung) * 28 + jong

so ``cho``/``jung``/``jong`` (initial/medial/final jamo) fall out with two
divisions. ``jong != 0`` means the syllable carries a batchim (final
consonant), which is what almost every Korean agreement rule keys off.
"""

from __future__ import annotations

from typing import Optional

SBASE = 0xAC00
SLAST = 0xD7A3
NJUNG = 21
NJONG = 28

#: Final consonants (jongseong) in Unicode order. Index 0 is "no batchim".
JONGSEONG = (
    "", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ",
    "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ",
    "ㅌ", "ㅍ", "ㅎ",
)

JONG_RIEUL = 8   # ㄹ -- the exception in 으로/로 and 은/는 after ㄹ stems
JONG_SSANG_SIOT = 20  # ㅆ -- marks past tense stems (했, 갔, 였 ...)


def is_syllable(ch: str) -> bool:
    """True if *ch* is a precomposed Hangul syllable (가-힣)."""
    return len(ch) == 1 and SBASE <= ord(ch) <= SLAST


def jongseong_index(ch: str) -> Optional[int]:
    """Return the final-consonant index of *ch*, or ``None`` if not a syllable.

    ``0`` means the syllable ends on a vowel.
    """
    if not is_syllable(ch):
        return None
    return (ord(ch) - SBASE) % NJONG


def has_batchim(ch: str) -> Optional[bool]:
    """True/False for Hangul syllables, ``None`` for anything else.

    ``None`` is deliberate: callers must decide what to do about Latin
    letters, digits and placeholders rather than silently guessing.
    """
    jong = jongseong_index(ch)
    if jong is None:
        return None
    return jong != 0


def ends_with_rieul(ch: str) -> bool:
    """True if *ch* ends on a ㄹ batchim (relevant to 으로/로, 으니/니 ...)."""
    return jongseong_index(ch) == JONG_RIEUL


def ends_with_ssang_siot(ch: str) -> bool:
    """True if *ch* ends on a ㅆ batchim -- i.e. a past-tense stem."""
    return jongseong_index(ch) == JONG_SSANG_SIOT


def has_hangul(text: str) -> bool:
    """True if *text* contains at least one Hangul syllable or jamo."""
    for ch in text:
        cp = ord(ch)
        if SBASE <= cp <= SLAST or 0x1100 <= cp <= 0x11FF or 0x3130 <= cp <= 0x318F:
            return True
    return False


def last_hangul_syllable(text: str) -> Optional[str]:
    """Last Hangul syllable in *text*, ignoring trailing non-Hangul."""
    for ch in reversed(text):
        if is_syllable(ch):
            return ch
    return None
