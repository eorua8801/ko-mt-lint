"""KO4xx -- translationese and typographic hygiene.

Nothing here is ungrammatical. It is the layer that makes a translation read
as a translation: pronouns English needs and Korean drops, passives stacked
on passives, spacing that followed the source instead of the target's rules.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Tuple

from ..core import Diagnostic, Rule, Segment, register
from .register import line_kind

#: Subjects English requires and Korean routinely omits. Fronting them on
#: every narration line is the single loudest tell of machine translation.
DEFAULT_PRONOUNS: Tuple[str, ...] = (
    "당신은", "당신이", "당신의", "당신을",
    "그것은", "그것이", "그것을",
    "그들은", "그들이",
    "그는", "그가", "그녀는", "그녀가",
)


@register
class FrontedPronoun(Rule):
    """A dropped-subject language being handed English's subject every time.

    Narration only -- dialogue legitimately addresses someone as 당신.
    Reported at ``info`` so it never fails a build on its own.
    """

    code = "KO401"
    name = "fronted-pronoun"
    summary = "나레이션 문두 대명사 과잉 (당신은 ...)"
    severity = "info"

    def __init__(self) -> None:
        self._pronouns = DEFAULT_PRONOUNS
        self._kinds = ("narration",)
        self._build()

    def configure(self, options: Dict[str, object]) -> None:
        extra = tuple(options.get("pronouns", ()) or ())
        self._pronouns = extra or DEFAULT_PRONOUNS
        kinds = options.get("apply_to")
        if kinds:
            self._kinds = tuple(str(k) for k in kinds)
        self._build()

    def _build(self) -> None:
        alts = "|".join(re.escape(p) for p in sorted(self._pronouns, key=len, reverse=True))
        self._pattern = re.compile(r"^\s*(%s)\s+" % alts)

    def check(self, seg: Segment) -> Iterable[Diagnostic]:
        if line_kind(seg) not in self._kinds:
            return ()
        m = self._pattern.match(seg.target)
        if not m:
            return ()
        fix = self._pattern.sub("", seg.target, count=1).strip()
        return (
            self.diag(
                seg,
                "문두 '%s' -- 한국어 나레이션에서는 주어를 생략하는 편이 자연스럽습니다"
                % m.group(1),
                col=m.start(1),
                fix=fix or None,
            ),
        )


#: ``(double-passive stem, corrected base)``. Only forms where the stem is
#: *already* passive are listed -- 만들어지다, 이루어지다, 알려지다 and
#: 밝혀지다 are standard Korean and deliberately absent.
DOUBLE_PASSIVES: Tuple[Tuple[str, str], ...] = (
    ("되어", "되다"),
    ("보여", "보이다"),
    ("불려", "불리다"),
    ("쓰여", "쓰이다"),
    ("씌여", "쓰이다"),
    ("잊혀", "잊히다"),
    ("읽혀", "읽히다"),
    ("닫혀", "닫히다"),
    ("열려", "열리다"),
    ("걸려", "걸리다"),
    ("팔려", "팔리다"),
    ("들려", "들리다"),
    ("나뉘어", "나뉘다"),
    ("풀려", "풀리다"),
    ("놓여", "놓이다"),
    ("모여", "모이다"),
    ("쌓여", "쌓이다"),
    ("덮여", "덮이다"),
    ("섞여", "섞이다"),
    ("바뀌어", "바뀌다"),
    ("찢겨", "찢기다"),
    ("꺾여", "꺾이다"),
    ("뽑혀", "뽑히다"),
    ("담겨", "담기다"),
    ("잠겨", "잠기다"),
)


@register
class DoublePassive(Rule):
    """이중피동 -- ``-어지다`` stacked on a stem that is already passive.

    ``보여지다`` is 보이다 (passive) plus 어지다 (passive again). Detection
    only: the corrected form varies by conjugation and a naive substitution
    produces worse Korean than the original, so the fix is left to a human.
    """

    code = "KO402"
    name = "double-passive"
    summary = "이중피동 (보여지다, 되어지다 ...)"
    severity = "warning"

    def __init__(self) -> None:
        self._pattern = re.compile(
            r"(%s)(지|진|질|져|졌|집|짐)"
            % "|".join(re.escape(p) for p, _ in DOUBLE_PASSIVES)
        )
        self._base = dict(DOUBLE_PASSIVES)

    def check(self, seg: Segment) -> Iterable[Diagnostic]:
        out: List[Diagnostic] = []
        for m in self._pattern.finditer(seg.target):
            stem = m.group(1)
            out.append(
                self.diag(
                    seg,
                    "이중피동 '%s' -- '%s' 계열로 고쳐 쓰세요" % (m.group(0), self._base[stem]),
                    col=m.start(),
                )
            )
        return out


@register
class Typography(Rule):
    """Spacing and punctuation that followed the source instead of Korean rules.

    Every pattern here compares against the source where one exists, so a
    string that legitimately carries padding or an ellipsis is left alone.
    """

    code = "KO403"
    name = "typography"
    summary = "구두점/공백 위생 (구두점 앞 공백, 중복 공백 ...)"
    severity = "info"

    _CHECKS = (
        (
            re.compile(r"\s+(?=[,.!?;:](?![.!?]))"),
            "",
            "구두점 앞 불필요한 공백",
        ),
        (
            re.compile(r",(?=[가-힣])"),
            ", ",
            "쉼표 뒤 공백 누락",
        ),
        (
            re.compile(r"[ \t]{2,}"),
            " ",
            "중복 공백",
        ),
    )

    def check(self, seg: Segment) -> Iterable[Diagnostic]:
        out: List[Diagnostic] = []
        fixed = seg.target
        for pattern, replacement, note in self._CHECKS:
            hits = list(pattern.finditer(seg.target))
            if not hits:
                continue
            # If the source has the same quirk it was authored deliberately.
            if seg.source and len(pattern.findall(seg.source)) >= len(hits):
                continue
            fixed = pattern.sub(replacement, fixed)
            out.append(self.diag(seg, "%s (%d곳)" % (note, len(hits)), col=hits[0].start()))

        stripped = seg.target.strip()
        if stripped != seg.target:
            source_padded = bool(seg.source and seg.source.strip() != seg.source)
            if not source_padded:
                fixed = fixed.strip()
                out.append(self.diag(seg, "앞뒤 불필요한 공백"))

        if out and fixed != seg.target:
            out = [
                Diagnostic(d.code, d.message, d.segment, d.severity, d.col, fixed)
                for d in out
            ]
        return out
