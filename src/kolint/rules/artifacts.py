"""KO1xx -- residue left behind by the machine that produced the translation.

Reasoning tags, another language's script, the source text passed through
untouched, the model explaining itself, a decoder falling into a loop. None
of these are translation mistakes; they are the pipeline leaking into the
output, and they are the errors that most embarrass a shipped build.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, List, Optional, Tuple

from ..core import Diagnostic, PatternRule, Rule, Segment, register
from ..hangul import has_hangul


@register
class ThinkingResidue(PatternRule):
    """Chain-of-thought markers that survived into the output.

    ``/think`` is qwen's; ``<think>``/``<thinking>`` cover the rest. Stripping
    them is always safe -- they were never meant to be shown.
    """

    code = "KO101"
    name = "thinking-residue"
    summary = "사고 과정 태그 잔여 (/think, <think> ...)"
    severity = "error"

    patterns = (
        (re.compile(r"\s*</?think(?:ing)?>\s*"), " ", "사고 태그 '{match}' 잔여"),
        (re.compile(r"\s*/think\.?\s*"), " ", "사고 태그 '{match}' 잔여"),
        (re.compile(r"\s*/no_?think\s*"), " ", "사고 태그 '{match}' 잔여"),
        (re.compile(r"<\|[a-z_]+\|>"), "", "특수 토큰 '{match}' 잔여"),
    )


@register
class ScriptLeak(Rule):
    """Characters from a script the source never contained.

    An English source that comes back with 战栗 in it means the model slipped
    languages. Comparing against the source makes this exact; with no source
    available it falls back to flagging kana and Han, which Korean game text
    almost never wants. Set ``allow_han = true`` if you write 한자 병기.
    """

    code = "KO102"
    name = "script-leak"
    summary = "원문에 없던 문자 체계 혼입 (간체자, 가나 ...)"
    severity = "error"

    def __init__(self) -> None:
        self._allow_han = False

    def configure(self, options: Dict[str, object]) -> None:
        self._allow_han = bool(options.get("allow_han", False))

    @staticmethod
    def _script_of(ch: str) -> str:
        cp = ord(ch)
        if 0x3040 <= cp <= 0x309F:
            return "히라가나"
        if 0x30A0 <= cp <= 0x30FF or 0x31F0 <= cp <= 0x31FF:
            return "가타카나"
        if 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF:
            return "한자"
        if 0x0400 <= cp <= 0x04FF:
            return "키릴"
        if 0x0600 <= cp <= 0x06FF:
            return "아랍"
        if 0x0E00 <= cp <= 0x0E7F:
            return "태국"
        return ""

    def check(self, seg: Segment) -> Iterable[Diagnostic]:
        source_scripts = set()
        if seg.source:
            for ch in seg.source:
                s = self._script_of(ch)
                if s:
                    source_scripts.add(s)

        seen: Dict[str, Tuple[int, str]] = {}
        for i, ch in enumerate(seg.target):
            script = self._script_of(ch)
            if not script or script in source_scripts:
                continue
            if script == "한자" and self._allow_han:
                continue
            if script not in seen:
                seen[script] = (i, ch)

        out: List[Diagnostic] = []
        for script, (col, ch) in seen.items():
            try:
                name = unicodedata.name(ch)
            except ValueError:
                name = "U+%04X" % ord(ch)
            where = "원문에 없는" if seg.source else "한국어 텍스트에 없어야 할"
            out.append(
                self.diag(
                    seg,
                    "%s %s 문자 '%s' (%s) 혼입" % (where, script, ch, name),
                    col=col,
                )
            )
        return out


@register
class Untranslated(Rule):
    """The source came back unchanged, or with no Korean in it at all.

    Guards against silently shipping English. Short strings and strings the
    source itself marks as symbolic (all caps, digits, punctuation) are
    skipped -- those are legitimately left alone.
    """

    code = "KO103"
    name = "untranslated"
    summary = "미번역 통과 (원문 그대로 / 한글 없음)"
    severity = "warning"

    _LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
    #: ``Inflict_Wounds``, ``ITEM_KEY`` -- code, not prose. Passing these
    #: through untranslated is the correct behaviour, not a missed string.
    _IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+")

    def __init__(self) -> None:
        self._min_latin_words = 2
        self._skip_identifiers = True
        self._ignore_pattern = None

    def configure(self, options: Dict[str, object]) -> None:
        self._min_latin_words = int(options.get("min_latin_words", 2))
        self._skip_identifiers = bool(options.get("skip_identifiers", True))
        raw = options.get("ignore_pattern")
        self._ignore_pattern = re.compile(str(raw)) if raw else None

    def check(self, seg: Segment) -> Iterable[Diagnostic]:
        target = seg.target.strip()
        if not target:
            return ()
        if self._skip_identifiers and self._IDENTIFIER.search(target):
            return ()
        if self._ignore_pattern is not None and self._ignore_pattern.search(target):
            return ()
        words = self._LATIN_WORD.findall(target)
        if len(words) < self._min_latin_words:
            return ()
        if has_hangul(target):
            return ()
        if seg.source and seg.source.strip() == target:
            return (
                self.diag(seg, "원문이 그대로 남아 있습니다 (번역 누락)", severity="error"),
            )
        return (self.diag(seg, "한글이 전혀 없는 라틴 문자 문자열 (번역 누락 의심)"),)


@register
class MetaCommentary(Rule):
    """The model talking about the translation instead of producing it.

    ``"번역: ..."``, ``"Here is the Korean translation:"``, a stray markdown
    fence, a parenthetical translator's note. All of it belongs in the log,
    not the string table.
    """

    code = "KO104"
    name = "meta-commentary"
    summary = "번역기 메타 발화 잔여 (번역:, Here is ..., ``` ...)"
    severity = "error"

    _PREFIXES = (
        re.compile(r"^\s*(?:번역|한국어\s*번역|translation|korean)\s*[:：]\s*", re.I),
        re.compile(r"^\s*(?:다음은|아래는)\s*[^\n]{0,40}?번역(?:입니다|이야|이에요)\s*[.:：]?\s*"),
        re.compile(
            r"^\s*here(?:'s| is)\s+the\s+[^\n]{0,40}?translation\s*[:：]?\s*", re.I
        ),
        re.compile(r"^\s*```[a-z]*\s*\n?"),
        re.compile(r"^\s*(?:sure|certainly|of course)[,!]\s*", re.I),
    )
    _SUFFIXES = (
        re.compile(r"\s*```\s*$"),
        re.compile(r"\s*\((?:번역자?\s*(?:주|노트)|translator'?s? note)[^)]{0,120}\)\s*$", re.I),
    )

    def check(self, seg: Segment) -> Iterable[Diagnostic]:
        out: List[Diagnostic] = []
        fixed = seg.target
        for pattern in self._PREFIXES:
            m = pattern.search(fixed)
            if m:
                out.append(self.diag(seg, "번역기 서두 '%s' 잔여" % m.group(0).strip(), col=m.start()))
                fixed = pattern.sub("", fixed, count=1)
        for pattern in self._SUFFIXES:
            m = pattern.search(fixed)
            if m:
                out.append(self.diag(seg, "번역기 후기 '%s' 잔여" % m.group(0).strip(), col=m.start()))
                fixed = pattern.sub("", fixed, count=1)
        if out and fixed.strip() and fixed != seg.target:
            out = [
                Diagnostic(d.code, d.message, d.segment, d.severity, d.col, fixed.strip())
                for d in out
            ]
        return out


@register
class RepetitionCollapse(Rule):
    """Decoder degeneration -- the same chunk emitted over and over.

    Catches both ``"그는 그는 그는"`` (repeated whitespace tokens) and
    ``"아아아아아아"`` (repeated character runs) without flagging ordinary
    emphasis like ``"하하하"``.

    Stylised source text repeats too -- ``"NOOOOOOO!"``, ``"Death. Death.
    Death."`` -- so when the source shows the same shape the translation is
    following it deliberately and nothing is reported.
    """

    code = "KO105"
    name = "repetition-collapse"
    summary = "동일 토큰/문구 반복 (디코더 붕괴)"
    severity = "error"

    def __init__(self) -> None:
        self._token_threshold = 3
        self._char_threshold = 6

    def configure(self, options: Dict[str, object]) -> None:
        self._token_threshold = int(options.get("token_threshold", 3))
        self._char_threshold = int(options.get("char_threshold", 6))

    def _source_repeats_tokens(self, source: Optional[str]) -> bool:
        if not source:
            return False
        tokens = source.split()
        run = 1
        for i in range(1, len(tokens)):
            run = run + 1 if tokens[i] == tokens[i - 1] else 1
            if run >= self._token_threshold:
                return True
        return False

    def _source_repeats_chars(self, source: Optional[str]) -> bool:
        if not source:
            return False
        pattern = r"(\S)\1{%d,}" % (self._char_threshold - 1)
        return bool(re.search(pattern, source))

    def check(self, seg: Segment) -> Iterable[Diagnostic]:
        out: List[Diagnostic] = []
        skip_tokens = self._source_repeats_tokens(seg.source)
        skip_chars = self._source_repeats_chars(seg.source)
        if skip_tokens and skip_chars:
            return ()

        tokens = [] if skip_tokens else seg.target.split()
        run_start = 0
        for i in range(1, len(tokens) + 1):
            same = i < len(tokens) and tokens[i] == tokens[run_start] and len(tokens[run_start]) > 1
            if same:
                continue
            run = i - run_start
            if run >= self._token_threshold:
                out.append(
                    self.diag(
                        seg,
                        "토큰 '%s'이 연속 %d회 반복" % (tokens[run_start], run),
                        col=seg.target.find(tokens[run_start]),
                    )
                )
            run_start = i

        if skip_chars:
            return out
        for m in re.finditer(r"(.)\1{%d,}" % (self._char_threshold - 1), seg.target):
            if m.group(1).isspace():
                continue
            out.append(
                self.diag(
                    seg,
                    "문자 '%s'이 %d회 연속 반복" % (m.group(1), len(m.group(0))),
                    col=m.start(),
                )
            )
        return out
