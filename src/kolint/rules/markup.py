"""KO2xx -- markup and placeholder fidelity against the source.

A dropped ``<i>`` is a cosmetic bug. A dropped ``{0}`` is a crash or a
sentence that reads ``"You found ."``. Both are mechanical to catch when the
source string is available, and invisible to a human reviewer skimming
thousands of lines.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, Iterable, List

from ..core import Diagnostic, Rule, Segment, register

TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9_-]*(?:=[^>\s]+)?(?:\s[^>]*)?/?>")

PLACEHOLDER_RE = re.compile(
    r"""(
        \{\{[^{}\n]{0,64}\}\}
      | \{[^{}\n]{0,64}\}
      | %(?:\d+\$)?[sdifuxc]
      | %%
      | \$\{[^{}\n]{0,64}\}
      | \$[A-Za-z_][A-Za-z0-9_]{0,32}
      | <<[^<>\n]{0,64}>>
      | \[[A-Z_][A-Z0-9_]{1,32}\]
      | %[A-Za-z_][A-Za-z0-9_]{0,32}%
    )""",
    re.VERBOSE,
)


def _describe(counter: Counter) -> str:
    return ", ".join("%s x%d" % (k, v) for k, v in sorted(counter.items()))


@register
class TagMismatch(Rule):
    """Rich-text tags present in the source but missing, extra, or reordered.

    Unity ``<color=#fff>``, ``<i>``, ``<size>``, BBCode, HTML -- all the same
    shape. Ordering matters for nesting, so a pure count check is not enough;
    this compares the tag sequence and reports the first divergence.
    """

    code = "KO201"
    name = "tag-mismatch"
    summary = "원문 대비 마크업 태그 불일치"
    severity = "error"

    def __init__(self) -> None:
        self._check_order = True

    def configure(self, options: Dict[str, object]) -> None:
        self._check_order = bool(options.get("check_order", True))

    def check(self, seg: Segment) -> Iterable[Diagnostic]:
        if seg.source is None:
            return ()
        src = TAG_RE.findall(seg.source)
        tgt = TAG_RE.findall(seg.target)
        if src == tgt:
            return ()

        src_count, tgt_count = Counter(src), Counter(tgt)
        missing = src_count - tgt_count
        extra = tgt_count - src_count

        out: List[Diagnostic] = []
        if missing:
            out.append(self.diag(seg, "원문에 있는 태그 누락: %s" % _describe(missing)))
        if extra:
            out.append(self.diag(seg, "원문에 없는 태그 추가: %s" % _describe(extra)))
        if not missing and not extra and self._check_order:
            out.append(
                self.diag(
                    seg,
                    "태그 순서 불일치: 원문 %s -> 번역 %s" % (src, tgt),
                    severity="warning",
                )
            )
        return out


@register
class PlaceholderMismatch(Rule):
    """Format placeholders dropped, duplicated, or invented.

    Missing ones break the sentence; invented ones break ``str.format``.
    Reported separately because the two have very different blast radii.
    """

    code = "KO202"
    name = "placeholder-mismatch"
    summary = "원문 대비 플레이스홀더 불일치 ({0}, %s ...)"
    severity = "error"

    def check(self, seg: Segment) -> Iterable[Diagnostic]:
        if seg.source is None:
            return ()
        src = Counter(m.group(0) for m in PLACEHOLDER_RE.finditer(seg.source))
        tgt = Counter(m.group(0) for m in PLACEHOLDER_RE.finditer(seg.target))
        if src == tgt:
            return ()

        out: List[Diagnostic] = []
        missing = src - tgt
        extra = tgt - src
        if missing:
            out.append(self.diag(seg, "플레이스홀더 누락: %s" % _describe(missing)))
        if extra:
            out.append(self.diag(seg, "원문에 없는 플레이스홀더: %s" % _describe(extra)))
        return out


@register
class LineBreakMismatch(Rule):
    """Newline count drift between source and translation.

    Game dialogue boxes and subtitle tracks are laid out by hand; a
    translation that merges two lines into one silently overflows the box.
    """

    code = "KO203"
    name = "linebreak-mismatch"
    summary = "원문 대비 줄바꿈 개수 불일치"
    severity = "warning"

    _BREAKS = ("\n", "\\n", "<br>", "<br/>", "<br />")

    def check(self, seg: Segment) -> Iterable[Diagnostic]:
        if seg.source is None:
            return ()
        out: List[Diagnostic] = []
        for token in self._BREAKS:
            s, t = seg.source.count(token), seg.target.count(token)
            if token == "\n":
                # "\\n" literals would otherwise be counted twice.
                s -= seg.source.count("\\n")
                t -= seg.target.count("\\n")
            if s != t:
                shown = token.replace("\n", "\\n")
                out.append(
                    self.diag(seg, "줄바꿈 '%s' 개수 불일치: 원문 %d -> 번역 %d" % (shown, s, t))
                )
        return out
