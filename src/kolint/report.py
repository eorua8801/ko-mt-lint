"""Diagnostic formatting."""

from __future__ import annotations

import json
import os
import sys
from typing import Dict, Iterable, List, Sequence

from .core import Diagnostic, Rule

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
COLORS = {"error": "\033[31m", "warning": "\033[33m", "info": "\033[36m"}


def supports_color(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


def _excerpt(text: str, col: int, width: int = 72) -> str:
    text = text.replace("\n", "\\n").replace("\t", "\\t")
    if len(text) <= width:
        return text
    start = max(0, col - width // 3)
    end = min(len(text), start + width)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + text[start:end] + suffix


def text_report(diagnostics: Sequence[Diagnostic], stream=None, color: bool = None) -> None:
    stream = stream or sys.stdout
    if color is None:
        color = supports_color(stream)

    def paint(s: str, code: str) -> str:
        return "%s%s%s" % (code, s, RESET) if color else s

    for d in diagnostics:
        seg = d.segment
        head = "%s:%d:%d" % (seg.location, seg.line, d.col + 1)
        sev = paint(d.severity.upper(), COLORS.get(d.severity, ""))
        code = paint(d.code, BOLD)
        stream.write("%s %s %s %s\n" % (head, sev, code, d.message))
        if seg.group:
            stream.write("%s    group: %s%s\n" % (DIM if color else "", seg.group, RESET if color else ""))
        stream.write("      %s\n" % _excerpt(seg.target, d.col))
        if d.fix is not None and d.fix != seg.target:
            stream.write("      %s %s\n" % (paint("fix ->", COLORS["info"]), _excerpt(d.fix, 0)))
        stream.write("\n")


def statistics_report(
    diagnostics: Sequence[Diagnostic],
    rules: Sequence[Rule],
    total_segments: int,
    stream=None,
    color: bool = None,
) -> None:
    stream = stream or sys.stdout
    if color is None:
        color = supports_color(stream)
    by_code: Dict[str, int] = {}
    fixable: Dict[str, int] = {}
    for d in diagnostics:
        by_code[d.code] = by_code.get(d.code, 0) + 1
        if d.fixable:
            fixable[d.code] = fixable.get(d.code, 0) + 1

    lookup = {r.code: r for r in rules}
    stream.write("\n%-8s %8s %8s  %s\n" % ("CODE", "COUNT", "FIXABLE", "RULE"))
    stream.write("%s\n" % ("-" * 72))
    for code in sorted(by_code, key=lambda c: (-by_code[c], c)):
        rule = lookup.get(code)
        stream.write(
            "%-8s %8d %8d  %s\n"
            % (code, by_code[code], fixable.get(code, 0), rule.summary if rule else "")
        )
    stream.write("%s\n" % ("-" * 72))
    stream.write(
        "%-8s %8d %8d  세그먼트 %d개 검사\n"
        % ("TOTAL", len(diagnostics), sum(fixable.values()), total_segments)
    )


def json_report(diagnostics: Sequence[Diagnostic], stream=None) -> None:
    stream = stream or sys.stdout
    payload = [
        {
            "code": d.code,
            "severity": d.severity,
            "message": d.message,
            "location": d.segment.location,
            "line": d.segment.line,
            "column": d.col + 1,
            "group": d.segment.group,
            "key": d.segment.key,
            "target": d.segment.target,
            "source": d.segment.source,
            "fix": d.fix,
        }
        for d in diagnostics
    ]
    json.dump(payload, stream, ensure_ascii=False, indent=2)
    stream.write("\n")


def github_report(diagnostics: Sequence[Diagnostic], stream=None) -> None:
    """GitHub Actions workflow-command annotations."""
    stream = stream or sys.stdout
    level = {"error": "error", "warning": "warning", "info": "notice"}
    for d in diagnostics:
        message = ("%s: %s" % (d.code, d.message)).replace("\n", " ").replace("%", "%25")
        stream.write(
            "::%s file=%s,line=%d,col=%d::%s\n"
            % (level.get(d.severity, "warning"), d.segment.location,
               d.segment.line, d.col + 1, message)
        )


def rules_table(rules: Iterable[Rule], stream=None) -> None:
    stream = stream or sys.stdout
    rows: List[Rule] = sorted(rules, key=lambda r: r.code)
    stream.write("%-8s %-10s %-22s %s\n" % ("CODE", "SEVERITY", "NAME", "SUMMARY"))
    stream.write("%s\n" % ("-" * 100))
    for r in rows:
        flags = []
        if not r.default_on:
            flags.append("opt-in")
        if r.needs_config:
            flags.append("needs config")
        suffix = "  [%s]" % ", ".join(flags) if flags else ""
        stream.write("%-8s %-10s %-22s %s%s\n" % (r.code, r.severity, r.name, r.summary, suffix))
