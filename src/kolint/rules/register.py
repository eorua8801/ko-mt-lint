"""KO3xx -- speech level (화계) consistency.

Korean grammar forces every sentence to commit to a speech level. English
does not, so a translator working line by line -- human or machine -- has
nothing anchoring the choice, and a single character drifts between
합니다체, 해요체 and 반말 across a conversation. Readers notice immediately;
diff-based review never catches it, because each line is fine on its own.

Generic i18n tooling has no concept of this. It is the whole reason these
rules operate on *groups* rather than segments.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, Iterable, List, Optional, Sequence

from ..core import Diagnostic, Rule, Segment, register, split_sentences, strip_trailing
from ..hangul import ends_with_ssang_siot

#: Canonical level ids and their Korean names.
LEVELS: Dict[str, str] = {
    "formal": "합니다체 (하십시오체)",
    "polite": "해요체",
    "plain": "다체 (해라체/문어체)",
    "casual": "반말 (해체)",
}

_FORMAL_ENDINGS = ("습니다", "ㅂ니다", "읍니다", "습니까", "ㅂ니까", "십시오", "ㅂ시다", "습디다")
_POLITE_ENDINGS = ("요", "죠", "쥬")

#: Multi-syllable 해체 endings with no noun homographs -- safe on their own.
_CASUAL_UNAMBIGUOUS = ("잖아", "거야", "는데", "구나", "는군", "더라", "을래", "ㄹ래")

#: Single-syllable endings that are also common noun finals: 야 (분야),
#: 래 (노래), 해 (이해), 자 (성직자), 지 (편지), 네 (동네). These only count
#: as a speech level when the segment actually terminates a sentence.
_CASUAL_AMBIGUOUS = (
    "아", "어", "야", "지", "네", "군", "걸", "래", "까", "나", "자",
    "렴", "든", "해", "돼", "봐", "줘", "와", "워", "게", "마",
)

_SENTENCE_FINAL = ".!?…~。！？"
_QUOTE_CHARS = " \t\"'“”‘’)]）」』>"


def _terminates_sentence(raw: str) -> bool:
    stripped = raw.rstrip(_QUOTE_CHARS)
    return bool(stripped) and stripped[-1] in _SENTENCE_FINAL


def detect_level(text: str) -> Optional[str]:
    """Classify the speech level of *text* by its final ending.

    Returns ``None`` whenever the ending is not clearly a predicate -- bare
    nouns, UI labels, interjections. Under-detecting is deliberate: a wrong
    level poisons the majority vote in :class:`RegisterDrift`, while a missing
    one merely costs a finding.

    Korean's single-syllable 해체 endings are homographic with common noun
    finals (성직자 vs. 가자, 노래 vs. 그래, 이해 vs. 안 해), so those are only
    accepted when the segment actually ends a sentence.
    """
    sentences = split_sentences(text)
    raw = sentences[-1] if sentences else text
    tail = strip_trailing(raw)
    if not tail:
        return None

    if (
        tail.endswith(_FORMAL_ENDINGS)
        or tail.endswith("니다")
        or tail.endswith("니까")
        or tail.endswith("시오")
    ):
        return "formal"
    if tail.endswith(_POLITE_ENDINGS):
        return "polite"
    if tail.endswith("다"):
        return "plain"
    if tail.endswith(_CASUAL_UNAMBIGUOUS):
        return "casual"
    # 했어 / 갔어 / 왔어 -- a ㅆ stem before 어 can only be a past-tense 해체 form.
    if len(tail) >= 2 and tail.endswith("어") and ends_with_ssang_siot(tail[-2]):
        return "casual"
    if tail.endswith(_CASUAL_AMBIGUOUS) and _terminates_sentence(raw):
        return "casual"
    return None


#: Line kinds are tracked separately -- narration is *supposed* to differ
#: from dialogue, and mixing them would make every group look inconsistent.
def line_kind(seg: Segment) -> str:
    probe = (seg.source or seg.target).strip()
    if not probe:
        return "narration"
    if probe[0] in ('"', "“", "「", "'", "‘"):
        return "dialogue"
    if probe[0] == "(":
        return "choice"
    return "narration"


_QUOTED_SPAN = re.compile(r'"[^"]*"|“[^”]*”|「[^」]*」|『[^』]*』')


def level_of(seg: Segment, kind: Optional[str] = None) -> Optional[str]:
    """Speech level of a segment, judged on the half that belongs to *kind*.

    Game lines routinely mix the two voices, and each half carries its own
    level::

        그녀가 말한다. "빨리 와!"        narration 다체 + dialogue 반말
        "아니요, 그랬어요," 그녀가 말한다.  dialogue 해요체 + narration 다체

    Reading such a line end-to-end would attribute the speaker's register to
    the narrator or the reverse, and report drift that is not there. So the
    other voice is removed first: narration drops quoted spans, dialogue
    keeps only them.
    """
    kind = kind or line_kind(seg)
    text = seg.target
    if kind == "narration":
        text = _QUOTED_SPAN.sub(" ", text)
    elif kind == "dialogue":
        spans = _QUOTED_SPAN.findall(text)
        if spans:
            text = " ".join(spans)
    if not text.strip():
        return None
    return detect_level(text)


@register
class RegisterDrift(Rule):
    """A group that mostly speaks one level, with stragglers in another.

    Only fires when the group has a clear majority: a genuinely mixed scene
    reports nothing rather than a hundred false alarms.
    """

    code = "KO301"
    name = "register-drift"
    summary = "그룹 내 문체 표류 (합니다체/해요체/반말 혼용)"
    severity = "warning"

    def __init__(self) -> None:
        self._min_segments = 5
        self._dominance = 0.6

    def configure(self, options: Dict[str, object]) -> None:
        self._min_segments = int(options.get("min_segments", 5))
        self._dominance = float(options.get("dominance", 0.6))

    def check_group(self, segments: Sequence[Segment]) -> Iterable[Diagnostic]:
        out: List[Diagnostic] = []
        by_kind: Dict[str, List[Segment]] = {}
        for seg in segments:
            by_kind.setdefault(line_kind(seg), []).append(seg)

        for kind, members in by_kind.items():
            levelled = [(s, level_of(s, kind)) for s in members]
            levelled = [(s, lv) for s, lv in levelled if lv]
            if len(levelled) < self._min_segments:
                continue
            counts = Counter(lv for _, lv in levelled)
            dominant, n = counts.most_common(1)[0]
            if n / float(len(levelled)) < self._dominance:
                continue
            for seg, lv in levelled:
                if lv == dominant:
                    continue
                out.append(
                    self.diag(
                        seg,
                        "'%s' 그룹의 %s는 주로 %s인데 이 줄만 %s (%d/%d)"
                        % (
                            seg.group or "<no group>",
                            kind,
                            LEVELS[dominant],
                            LEVELS[lv],
                            counts[lv],
                            len(levelled),
                        ),
                    )
                )
        return out


@register
class SpeakerRegister(Rule):
    """A speaker breaking the level their profile declares.

    Configure with a table mapping group -> level::

        [KO302.speakers]
        Archivist = "formal"
        Scout     = "casual"
        Envoy     = "polite"

    This turns "how does this character talk" from tribal knowledge held by
    one translator into a contract the build can enforce.
    """

    code = "KO302"
    name = "speaker-register"
    summary = "화자 프로파일과 다른 문체 (설정 필요)"
    severity = "warning"
    needs_config = True

    def __init__(self) -> None:
        self._speakers: Dict[str, str] = {}
        self._kinds = ("dialogue",)

    def configure(self, options: Dict[str, object]) -> None:
        raw = options.get("speakers", {}) or {}
        speakers: Dict[str, str] = {}
        for group, level in dict(raw).items():
            level = str(level).strip().lower()
            if level not in LEVELS:
                raise ValueError(
                    "KO302: unknown speech level %r for %r (expected one of %s)"
                    % (level, group, ", ".join(sorted(LEVELS)))
                )
            speakers[str(group)] = level
        self._speakers = speakers
        kinds = options.get("apply_to")
        if kinds:
            self._kinds = tuple(str(k) for k in kinds)

    def check_group(self, segments: Sequence[Segment]) -> Iterable[Diagnostic]:
        if not self._speakers or not segments:
            return ()
        group = segments[0].group
        expected = self._resolve(group)
        if expected is None:
            return ()

        out: List[Diagnostic] = []
        for seg in segments:
            kind = line_kind(seg)
            if kind not in self._kinds:
                continue
            actual = level_of(seg, kind)
            if actual is None or actual == expected:
                continue
            out.append(
                self.diag(
                    seg,
                    "화자 '%s'는 %s로 말해야 하는데 이 줄은 %s"
                    % (group, LEVELS[expected], LEVELS[actual]),
                )
            )
        return out

    def _resolve(self, group: Optional[str]) -> Optional[str]:
        if not group:
            return None
        if group in self._speakers:
            return self._speakers[group]
        # Allow "Archivist" to cover "NPC_Archivist", "EP_Archivist", ...
        for name, level in self._speakers.items():
            if name and name in group:
                return level
        return None
