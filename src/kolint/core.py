"""Core data model: segments, diagnostics, and the rule protocol."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Sequence

Severity = str  # "error" | "warning" | "info"

SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2}


@dataclass
class Segment:
    """One translatable unit.

    ``target`` is the Korean text under inspection. ``source`` is the original
    it was translated from -- optional, but several rules get much sharper when
    it is present (tag matching, script-leak detection, untranslated
    passthrough). ``group`` buckets segments that should share a register: a
    speaker, a dialogue file, a UI screen.
    """

    target: str
    source: Optional[str] = None
    group: Optional[str] = None
    key: Optional[str] = None
    location: str = "<input>"
    line: int = 0
    meta: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    segment: Segment
    severity: Severity = "warning"
    #: Character offset within ``segment.target`` where the problem starts.
    col: int = 0
    #: Replacement for ``segment.target``. ``None`` when the rule cannot fix it.
    fix: Optional[str] = None

    @property
    def fixable(self) -> bool:
        return self.fix is not None


class Rule:
    """Base class for a single check.

    Subclasses implement :meth:`check` (per segment) or :meth:`check_group`
    (across a group of segments sharing ``Segment.group``).
    """

    code: str = ""
    name: str = ""
    summary: str = ""
    severity: Severity = "warning"
    #: Rules off unless explicitly selected -- heuristics with known false
    #: positives live here so the default run stays trustworthy.
    default_on: bool = True
    #: Set when the rule needs configuration (a glossary, speaker profiles)
    #: and should stay quiet when that configuration is absent.
    needs_config: bool = False

    def configure(self, options: Dict[str, object]) -> None:
        """Hook for rules that read settings out of ``kolint.toml``."""

    def check(self, seg: Segment) -> Iterable[Diagnostic]:
        return ()

    def check_group(self, segments: Sequence[Segment]) -> Iterable[Diagnostic]:
        return ()

    # -- helpers -----------------------------------------------------------

    def diag(
        self,
        seg: Segment,
        message: str,
        col: int = 0,
        fix: Optional[str] = None,
        severity: Optional[Severity] = None,
    ) -> Diagnostic:
        return Diagnostic(
            code=self.code,
            message=message,
            segment=seg,
            severity=severity or self.severity,
            col=col,
            fix=fix,
        )


class PatternRule(Rule):
    """A rule expressed as a list of ``(compiled_pattern, replacement)`` pairs.

    ``replacement`` may be ``None`` for detect-only patterns. Every match
    produces one diagnostic; when all matched patterns are replaceable the
    diagnostic carries a fix for the whole segment.
    """

    #: ``(pattern, replacement, human_readable_note)``
    patterns: Sequence = ()

    def check(self, seg: Segment) -> Iterable[Diagnostic]:
        out: List[Diagnostic] = []
        for pattern, replacement, note in self.patterns:
            for m in pattern.finditer(seg.target):
                fix = None
                if replacement is not None:
                    fixed = pattern.sub(replacement, seg.target)
                    if fixed != seg.target:
                        fix = fixed
                out.append(
                    self.diag(
                        seg,
                        note.format(match=m.group(0)),
                        col=m.start(),
                        fix=fix,
                    )
                )
        return out


_REGISTRY: Dict[str, Rule] = {}


def register(rule_cls):
    """Class decorator adding a rule to the global registry."""
    rule = rule_cls()
    if not rule.code:
        raise ValueError("%s has no code" % rule_cls.__name__)
    if rule.code in _REGISTRY:
        raise ValueError("duplicate rule code %s" % rule.code)
    _REGISTRY[rule.code] = rule
    return rule_cls


def all_rules() -> List[Rule]:
    return [_REGISTRY[c] for c in sorted(_REGISTRY)]


def get_rule(code: str) -> Optional[Rule]:
    return _REGISTRY.get(code)


def expand_selector(selector: str) -> List[str]:
    """Expand ``KO0``/``KO001``/``all`` into concrete rule codes."""
    selector = selector.strip()
    if not selector:
        return []
    if selector.lower() == "all":
        return sorted(_REGISTRY)
    return sorted(c for c in _REGISTRY if c.startswith(selector.upper()))


def resolve_selection(
    select: Optional[Sequence[str]] = None,
    ignore: Optional[Sequence[str]] = None,
    extend_select: Optional[Sequence[str]] = None,
) -> List[str]:
    """Turn CLI/config selectors into the final ordered list of rule codes."""
    if select:
        chosen = set()
        for sel in select:
            chosen.update(expand_selector(sel))
    else:
        chosen = {c for c, r in _REGISTRY.items() if r.default_on}
    for sel in extend_select or ():
        chosen.update(expand_selector(sel))
    for sel in ignore or ():
        chosen.difference_update(expand_selector(sel))
    return sorted(chosen)


# ---------------------------------------------------------------------------
# Sentence splitting -- used by register detection and a few style rules.
# ---------------------------------------------------------------------------

_SENT_SPLIT = re.compile(r"(?<=[.!?…！？])\s+|\n+")
# Trailing commas matter here: dialogue carries the English speech-tag comma
# inside the quotation ("...했어요," 그녀가 말한다), and the ending we need to
# read sits just before it.
_TRAILING_JUNK = re.compile(r"[\s.!?…,、，\"'“”‘’)\]）」』]+$")


def split_sentences(text: str) -> List[str]:
    return [s for s in (p.strip() for p in _SENT_SPLIT.split(text)) if s]


def strip_trailing(text: str) -> str:
    """Drop trailing punctuation/quotes so the final ending is inspectable."""
    return _TRAILING_JUNK.sub("", text.strip())


def iter_groups(segments: Iterable[Segment]) -> Iterator[List[Segment]]:
    """Yield segments bucketed by ``Segment.group``, preserving input order."""
    buckets: Dict[Optional[str], List[Segment]] = {}
    order: List[Optional[str]] = []
    for seg in segments:
        if seg.group not in buckets:
            buckets[seg.group] = []
            order.append(seg.group)
        buckets[seg.group].append(seg)
    for g in order:
        yield buckets[g]
