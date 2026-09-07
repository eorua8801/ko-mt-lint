"""kolint -- a linter for Korean machine-translation and LLM output.

Existing Korean tooling *generates* correct particles. Nothing checks text
that already exists. This package does the second thing: it reads translated
strings and reports the mechanical failures that survive both a good prompt
and a fast human review -- stacked copulas, tense/ending mismatches, script
leakage, dropped markup, and speech level drifting inside one speaker.

    from kolint import lint_text
    lint_text("그는 성직자을 보았는다.")
"""

from __future__ import annotations

from typing import List, Optional, Sequence

__version__ = "0.1.0"

from .core import Diagnostic, Rule, Segment, all_rules, get_rule  # noqa: E402
from . import rules as _rules  # noqa: E402,F401  (populates the registry)
from .engine import build_rules, counts_by_code, exceeds, fix, run  # noqa: E402

__all__ = [
    "__version__",
    "Diagnostic",
    "Rule",
    "Segment",
    "all_rules",
    "get_rule",
    "build_rules",
    "counts_by_code",
    "exceeds",
    "fix",
    "run",
    "lint_text",
    "lint_segments",
]


def lint_text(
    target: str,
    source: Optional[str] = None,
    select: Optional[Sequence[str]] = None,
) -> List[Diagnostic]:
    """Lint a single string. Convenience wrapper around :func:`run`."""
    return lint_segments([Segment(target=target, source=source)], select=select)


def lint_segments(
    segments: Sequence[Segment],
    select: Optional[Sequence[str]] = None,
    ignore: Optional[Sequence[str]] = None,
) -> List[Diagnostic]:
    """Lint prepared :class:`Segment` objects with the default rule set."""
    return run(segments, build_rules(select=select, ignore=ignore))
