"""Running rules over segments, and applying their fixes."""

from __future__ import annotations

import copy
from typing import Dict, Iterable, List, Optional, Sequence

from .config import Config
from .core import (
    Diagnostic,
    Rule,
    SEVERITY_ORDER,
    Segment,
    get_rule,
    iter_groups,
    resolve_selection,
)


def build_rules(config: Optional[Config] = None,
                select: Optional[Sequence[str]] = None,
                ignore: Optional[Sequence[str]] = None,
                extend_select: Optional[Sequence[str]] = None) -> List[Rule]:
    """Resolve selectors into configured rule instances, in code order."""
    config = config or Config()
    codes = resolve_selection(
        select if select is not None else config.select,
        list(ignore or []) + list(config.ignore),
        list(extend_select or []) + list(config.extend_select),
    )
    rules: List[Rule] = []
    for code in codes:
        registered = get_rule(code)
        if registered is None:
            continue
        options = config.options_for(code)
        if registered.needs_config and not options:
            continue  # nothing to check against; stay quiet rather than guess
        # The registry holds one shared instance per rule. Copy before
        # configuring so two rule sets built in the same process (tests,
        # a long-lived service, a batch over several projects) cannot leak
        # settings into each other.
        rule = copy.copy(registered)
        rule.configure(options)
        rules.append(rule)
    return rules


def run(segments: Sequence[Segment], rules: Sequence[Rule]) -> List[Diagnostic]:
    """Run every rule over *segments*, returning diagnostics in file order."""
    out: List[Diagnostic] = []
    per_segment = [r for r in rules if type(r).check is not Rule.check]
    per_group = [r for r in rules if type(r).check_group is not Rule.check_group]

    for seg in segments:
        for rule in per_segment:
            out.extend(rule.check(seg))

    if per_group:
        for group in iter_groups(segments):
            for rule in per_group:
                out.extend(rule.check_group(group))

    out.sort(key=lambda d: (d.segment.location, d.segment.line, d.col, d.code))
    return out


def fix(segments: Sequence[Segment], rules: Sequence[Rule], max_passes: int = 8) -> int:
    """Apply fixable diagnostics in place. Returns the number of edits made.

    Fixes rewrite the whole target, so they are applied one at a time and the
    rules re-run until the segment stops changing -- that way two rules
    touching the same string compose instead of clobbering each other.
    """
    per_segment = [r for r in rules if type(r).check is not Rule.check]
    applied = 0
    for seg in segments:
        for _ in range(max_passes):
            changed = False
            for rule in per_segment:
                for diag in rule.check(seg):
                    if diag.fix is None or diag.fix == seg.target:
                        continue
                    seg.target = diag.fix
                    applied += 1
                    changed = True
                    break
                if changed:
                    break
            if not changed:
                break
    return applied


def exceeds(diagnostics: Iterable[Diagnostic], level: str) -> bool:
    """True if any diagnostic is at or above *level* (info < warning < error)."""
    threshold = SEVERITY_ORDER.get(level, 1)
    return any(SEVERITY_ORDER.get(d.severity, 1) >= threshold for d in diagnostics)


def counts_by_code(diagnostics: Iterable[Diagnostic]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for d in diagnostics:
        out[d.code] = out.get(d.code, 0) + 1
    return out
