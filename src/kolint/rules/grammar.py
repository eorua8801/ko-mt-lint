"""KO0xx -- conjugation and particle agreement errors.

These are the failures that machine translation and LLMs produce constantly
and that no amount of prompt engineering removes reliably, because they are
mechanical: the model picks a particle or an ending without checking the
final consonant of the word it just wrote.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ..core import Diagnostic, PatternRule, Rule, Segment, register
from ..hangul import (
    ends_with_ssang_siot,
    has_batchim,
    is_syllable,
    last_hangul_syllable,
)


@register
class DuplicateParticle(PatternRule):
    """Two case particles stacked on one noun -- ``그를을``.

    Deliberately tiny. Korean writes particles with no space, so most
    "duplicated particle" sequences are really a noun whose last syllable
    happens to be a particle, and flagging them does more harm than good:

    * ``과와`` -- 치과와, 사과와, 효과와, 결과와 are noun + 와 ("and").
      Every occurrence of this pattern in a 70k-line corpus was a false
      positive, which is why it is gone.
    * ``을를`` -- 마을를, 가을를 are genuinely wrong, but the repair is
      ``마을을``, not ``마을``; collapsing the pair would delete the particle.
      Left to :class:`JosaAgreement` (KO007), which knows the noun.

    What remains are sequences with no noun-boundary reading at all. The
    copula equivalent (``이입니다``) lives in :class:`RedundantCopula`.
    """

    code = "KO001"
    name = "duplicate-particle"
    summary = "조사 중복 (를을, 은는 ...)"
    severity = "error"

    patterns = (
        (re.compile(r"를을"), "를", "조사 중복 '{match}'"),
        (re.compile(r"은는"), "은", "조사 중복 '{match}'"),
        (re.compile(r"는은"), "는", "조사 중복 '{match}'"),
        # NB: no 이가 pattern -- 고양이가 / 아이가 are ordinary noun+particle.
    )


#: Nouns that genuinely end in 이. After these, ``이입니다`` / ``이이다`` are
#: correct and KO004 must stay silent. The list is necessarily incomplete --
#: -이 is a productive nominaliser -- which is exactly why KO004 is opt-in.
I_FINAL_NOUNS: Tuple[str, ...] = (
    # -이 nominalisations
    "길이", "높이", "깊이", "넓이", "먹이", "놀이", "벌이", "구이",
    # plain nouns
    "나이", "사이", "종이", "아이", "오이", "고양이", "곰팡이", "호랑이",
    "지팡이", "손잡이", "목걸이", "귀걸이", "재떨이",
    # -쟁이 / -둥이 / -은이 suffixes
    "겁쟁이", "멍청이", "개구쟁이", "어린이", "젖은이", "늘은이", "막둥이",
)


@register
class RedundantCopula(Rule):
    """``검이입니다`` -- the copula 이- attached to a form that already carries it.

    Opt in with ``--select KO004``. The pattern is genuinely ambiguous:
    ``길이입니다`` ("it is the length") and ``고양이이다`` ("it is a cat") are
    *correct*, because 길이 and 고양이 are themselves nouns ending in 이.
    Telling those apart from a doubled copula needs a dictionary, so this
    rule ships a stoplist of common 이-final nouns and asks you to read the
    diff. It is high yield when your pipeline rewrites sentence endings --
    that is where the doubling comes from -- and noise otherwise.
    """

    code = "KO004"
    name = "redundant-copula"
    summary = "계사 중복 가능 (이입니다, 이이다) -- 검토 필요, 기본 비활성"
    severity = "warning"
    default_on = False

    _FORMS = (
        ("이입니다", "입니다"),
        ("이입니까", "입니까"),
        ("이이다", "이다"),
        ("이이에요", "이에요"),
        ("이이야", "이야"),
        ("이이었", "이었"),
    )

    def __init__(self) -> None:
        self._stopwords = tuple(I_FINAL_NOUNS)

    def configure(self, options: Dict[str, object]) -> None:
        extra = tuple(options.get("extra_nouns", ()) or ())
        self._stopwords = tuple(I_FINAL_NOUNS) + extra

    def _preceded_by_noun(self, text: str, match_start: int) -> bool:
        """True if the 이 belongs to a noun rather than to a doubled copula."""
        head = text[:match_start + 1]  # include the 이 that opens the match
        # A standalone 이 is the dependent noun "one/person": 만든 이이다
        # ("it is the one who made it") is correct and must not be collapsed.
        if match_start == 0 or text[match_start - 1].isspace():
            return True
        return any(head.endswith(noun) for noun in self._stopwords)

    def check(self, seg: Segment) -> Iterable[Diagnostic]:
        out: List[Diagnostic] = []
        fixed = seg.target
        for bad, good in self._FORMS:
            start = 0
            while True:
                idx = seg.target.find(bad, start)
                if idx < 0:
                    break
                start = idx + 1
                if self._preceded_by_noun(seg.target, idx):
                    continue
                fixed = fixed.replace(bad, good, 1)
                out.append(
                    self.diag(
                        seg,
                        "계사 중복으로 보입니다 -- '%s' -> '%s' (앞말이 이-말음 명사인지 확인하세요)"
                        % (bad, good),
                        col=idx,
                    )
                )
        if out and fixed != seg.target:
            out = [
                Diagnostic(d.code, d.message, d.segment, d.severity, d.col, fixed)
                for d in out
            ]
        return out


@register
class PastTenseNeunda(Rule):
    """``했는다`` -- present-tense ``-는다`` bolted onto a past-tense stem.

    A stem ending on ㅆ (했/갔/였/있/샀 ...) is already past; ``-는다`` marks
    present. The combination cannot occur in Korean, so this is a zero
    false-positive check driven purely by the final consonant.
    """

    code = "KO002"
    name = "past-tense-neunda"
    summary = "과거 어간 + '는다' (했는다, 이었는다 ...)"
    severity = "error"

    _NEUNDA = re.compile(r"(.)는다")

    def check(self, seg: Segment) -> Iterable[Diagnostic]:
        out: List[Diagnostic] = []
        fixed = seg.target
        for m in self._NEUNDA.finditer(seg.target):
            stem = m.group(1)
            if not ends_with_ssang_siot(stem):
                continue
            bad = m.group(0)
            good = stem + "다"
            fixed = fixed.replace(bad, good)
            out.append(
                self.diag(
                    seg,
                    "과거 어간 뒤 '는다' -- '%s' -> '%s'" % (bad, good),
                    col=m.start(),
                )
            )
        if out and fixed != seg.target:
            out = [
                Diagnostic(d.code, d.message, d.segment, d.severity, d.col, fixed)
                for d in out
            ]
        return out


#: Descriptive verbs (형용사). ``-는다`` never attaches to these; ``-다`` does.
#
# Excluded on purpose: 적 (적다 "write down" -> 적는다 is valid) and
# 밝 (밝다 "dawn breaks" -> 밝는다 is attested). Both have verb readings.
ADJECTIVE_STEMS: Tuple[str, ...] = (
    "좋", "싫", "없", "많", "작", "크", "낮", "높", "길", "짧",
    "넓", "좁", "깊", "얇", "어둡", "덩", "춥", "뜨겁", "차갑",
    "무겁", "가벼", "빠르", "느리", "쉽", "어렵", "예쁜", "아름답",
    "귀엽", "무섭", "슬프", "기쁜", "아프", "배고프", "행복하", "달",
    "쓰", "맵", "짜", "시", "뗫",
)

#: 하다-adjectives: ``중요하다`` -> ``중요한다`` is a classic MT slip.
HADA_ADJECTIVES: Tuple[str, ...] = (
    "중요", "필요", "가능", "불가능", "강력", "특별", "명확", "위험",
    "이상", "조용", "복잡", "단순", "정확", "확실", "충분", "부족",
    "적절", "편안", "불편", "심각", "완벽", "평범", "친절", "공평",
    "다양", "유사", "동일", "안전", "선명", "거대", "미묘", "어색",
    "당연", "분명", "솔직", "성실", "냉정", "침착", "화려", "소중",
)


@register
class AdjectiveNeunda(Rule):
    """``좋는다`` / ``중요한다`` -- present ``-는다`` on a descriptive verb.

    Korean descriptive verbs take a bare ``-다``. Driven by a curated stem
    list rather than a guess, so it stays precise; extend it via
    ``[KO003] extra_stems`` in the config.
    """

    code = "KO003"
    name = "adjective-neunda"
    summary = "형용사 + '는다/ㄴ다' (좋는다, 중요한다 ...)"
    severity = "error"

    def __init__(self) -> None:
        self._extra_stems: Tuple[str, ...] = ()
        self._extra_hada: Tuple[str, ...] = ()
        self._build()

    def configure(self, options: Dict[str, object]) -> None:
        self._extra_stems = tuple(options.get("extra_stems", ()) or ())
        self._extra_hada = tuple(options.get("extra_hada", ()) or ())
        self._build()

    def _build(self) -> None:
        stems = tuple(ADJECTIVE_STEMS) + self._extra_stems
        hada = tuple(HADA_ADJECTIVES) + self._extra_hada
        self._pairs: List[Tuple[re.Pattern, str]] = []
        for stem in stems:
            self._pairs.append((re.compile(re.escape(stem) + r"는다"), stem + "다"))
        for word in hada:
            self._pairs.append((re.compile(re.escape(word) + r"한다"), word + "하다"))

    def check(self, seg: Segment) -> Iterable[Diagnostic]:
        out: List[Diagnostic] = []
        fixed = seg.target
        for pattern, replacement in self._pairs:
            for m in pattern.finditer(seg.target):
                out.append(
                    self.diag(
                        seg,
                        "형용사에 '는다/ㄴ다' -- '%s' -> '%s'" % (m.group(0), replacement),
                        col=m.start(),
                    )
                )
            fixed = pattern.sub(replacement, fixed)
        if out and fixed != seg.target:
            out = [
                Diagnostic(d.code, d.message, d.segment, d.severity, d.col, fixed)
                for d in out
            ]
        return out


# ---------------------------------------------------------------------------
# Particle agreement
# ---------------------------------------------------------------------------

#: ``after_batchim`` / ``after_vowel`` pairs for the batchim-sensitive particles.
JOSA_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("은", "는"),
    ("이", "가"),
    ("을", "를"),
    ("과", "와"),
    ("이나", "나"),
    ("이란", "란"),
    ("이라", "라"),
    ("이며", "며"),
    ("이랑", "랑"),
    ("으로", "로"),
    ("으로써", "로써"),
    ("으로서", "로서"),
    ("아", "야"),
)

_PLACEHOLDER = re.compile(
    r"""(
        \{[^{}\n]{0,64}\}          # {0} {name} {player_name}
      | %(?:\d+\$)?[sdifux]        # %s %d %1$s
      | \$\{[^{}\n]{0,64}\}        # ${name}
      | <<[^<>\n]{0,64}>>          # <<name>>
      | \[[A-Za-z_][A-Za-z0-9_]{0,32}\]  # [PLAYER]
      | %[A-Za-z_][A-Za-z0-9_]{0,32}%    # %PLAYER%
    )""",
    re.VERBOSE,
)

#: Particles whose correct form depends on a batchim we cannot see at lint time.
_RISKY_AFTER_PLACEHOLDER = tuple(
    sorted({a for a, _ in JOSA_PAIRS} | {b for _, b in JOSA_PAIRS}, key=len, reverse=True)
)


@register
class PlaceholderJosa(Rule):
    """A batchim-sensitive particle directly after a runtime placeholder.

    ``{name}을`` is a bug waiting for the first vowel-final name. There is no
    way to pick correctly at authoring time, so the fix is either a dual form
    (``을(를)``) or a particle-resolving template helper. This is the check
    those two dozen josa *generator* libraries exist to make unnecessary --
    and that nothing on PyPI actually performs.
    """

    code = "KO005"
    name = "placeholder-josa"
    summary = "플레이스홀더 뒤 받침 의존 조사 ({name}을)"
    severity = "error"

    def __init__(self) -> None:
        self._dual_ok = True

    def configure(self, options: Dict[str, object]) -> None:
        self._dual_ok = bool(options.get("allow_dual_form", True))

    def check(self, seg: Segment) -> Iterable[Diagnostic]:
        out: List[Diagnostic] = []
        for m in _PLACEHOLDER.finditer(seg.target):
            tail = seg.target[m.end():]
            if not tail:
                continue
            for josa in _RISKY_AFTER_PLACEHOLDER:
                if not tail.startswith(josa):
                    continue
                rest = tail[len(josa):]
                # 이/가 as part of a longer word ("{n}가지") is not a particle.
                if rest and is_syllable(rest[0]):
                    break
                if self._dual_ok and rest.startswith("("):
                    break  # already written as 을(를)
                partner = self._partner(josa)
                suggestion = "%s(%s)" % (josa, partner) if partner else josa
                out.append(
                    self.diag(
                        seg,
                        "플레이스홀더 '%s' 뒤의 '%s'는 런타임 값의 받침에 따라 달라집니다"
                        " -- '%s' 형태나 조사 처리 헬퍼를 쓰세요"
                        % (m.group(0), josa, suggestion),
                        col=m.end(),
                    )
                )
                break
        return out

    @staticmethod
    def _partner(josa: str) -> Optional[str]:
        for a, b in JOSA_PAIRS:
            if josa == a:
                return b
            if josa == b:
                return a
        return None


@register
class GlossaryJosa(Rule):
    """Wrong particle after a known glossary term.

    Because the noun is known exactly, the correct particle is a pure
    function of its last syllable -- no morphological analysis, no guessing,
    no false positives. Configure with ``[KO006] terms = [...]``.
    """

    code = "KO006"
    name = "glossary-josa"
    summary = "용어집 항목 뒤 조사 불일치 (성직자을)"
    severity = "error"
    needs_config = True

    def __init__(self) -> None:
        self._terms: Tuple[str, ...] = ()
        self._pattern: Optional[re.Pattern] = None

    def configure(self, options: Dict[str, object]) -> None:
        terms = tuple(options.get("terms", ()) or ())
        self._terms = tuple(sorted(terms, key=len, reverse=True))
        if self._terms:
            alts = "|".join(re.escape(t) for t in self._terms)
            josa = "|".join(
                sorted(
                    {a for a, _ in JOSA_PAIRS} | {b for _, b in JOSA_PAIRS},
                    key=len,
                    reverse=True,
                )
            )
            self._pattern = re.compile("(%s)(%s)(?![가-힣])" % (alts, josa))
        else:
            self._pattern = None

    def check(self, seg: Segment) -> Iterable[Diagnostic]:
        if self._pattern is None:
            return ()
        out: List[Diagnostic] = []
        fixed = seg.target
        for m in self._pattern.finditer(seg.target):
            term, josa = m.group(1), m.group(2)
            correct = correct_josa(term, josa)
            if correct is None or correct == josa:
                continue
            out.append(
                self.diag(
                    seg,
                    "'%s' 뒤에는 '%s'가 아니라 '%s' -- '%s%s'"
                    % (term, josa, correct, term, correct),
                    col=m.start(2),
                )
            )
            fixed = fixed.replace(term + josa, term + correct)
        if out and fixed != seg.target:
            out = [
                Diagnostic(d.code, d.message, d.segment, d.severity, d.col, fixed)
                for d in out
            ]
        return out


def correct_josa(word: str, josa: str) -> Optional[str]:
    """Return the particle *word* actually requires, or ``None`` if unknown."""
    syl = last_hangul_syllable(word)
    if syl is None:
        return None
    batchim = has_batchim(syl)
    if batchim is None:
        return None
    for after_batchim, after_vowel in JOSA_PAIRS:
        if josa not in (after_batchim, after_vowel):
            continue
        # 으로/로 take the vowel form after a ㄹ batchim as well.
        if after_batchim.startswith("으로") and syl and _is_rieul(syl):
            return after_vowel
        return after_batchim if batchim else after_vowel
    return None


def _is_rieul(ch: str) -> bool:
    from ..hangul import ends_with_rieul

    return ends_with_rieul(ch)


#: Words that merely *look* like noun+particle. Guards the opt-in KO007.
_JOSA_STOPWORDS = frozenset(
    """
    가을 가족 가지 거울 겨울 결과 경우 계약 고을 과일 과정 관계 구름 그것
    기울 나라 나이 나물 노을 다음 마을 마음 모을 무엇 물을 바다 바람 방을
    보이 사이 사물 새로 서로 소리 아이 아침 얼음 여름 오늘 오이 이유 이름
    자리 저녁 정도 조을 지금 처음 하나 하늘 학교 한글 형태
    """.split()
)


@register
class JosaAgreement(Rule):
    """General noun+particle agreement. Heuristic -- opt in with ``--select KO007``.

    Korean is written without word boundaries around particles, so a bare
    regex cannot always tell ``가을`` (autumn) from ``가`` + ``을``. Without a
    morphological analyser this rule trades recall for a stopword list; it is
    off by default so a plain ``kolint check`` stays trustworthy. Prefer
    KO005/KO006, which are exact.
    """

    code = "KO007"
    name = "josa-agreement"
    summary = "일반 명사 + 조사 일치 (휴리스틱, 기본 비활성)"
    severity = "warning"
    default_on = False

    _WORD_JOSA = re.compile(r"([가-힣]{2,})(은|는|이|가|을|를|과|와)(?![가-힣])")

    def __init__(self) -> None:
        self._stopwords = set(_JOSA_STOPWORDS)

    def configure(self, options: Dict[str, object]) -> None:
        self._stopwords = set(_JOSA_STOPWORDS) | set(options.get("stopwords", ()) or ())

    def check(self, seg: Segment) -> Iterable[Diagnostic]:
        out: List[Diagnostic] = []
        for m in self._WORD_JOSA.finditer(seg.target):
            whole, josa = m.group(0), m.group(2)
            if whole in self._stopwords:
                continue
            stem = m.group(1)
            correct = correct_josa(stem, josa)
            if correct is None or correct == josa:
                continue
            out.append(
                self.diag(
                    seg,
                    "조사 불일치 가능 -- '%s' 뒤에는 '%s'로 보입니다 ('%s%s')"
                    % (stem, correct, stem, correct),
                    col=m.start(2),
                )
            )
        return out
