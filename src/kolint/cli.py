"""Command line interface."""

from __future__ import annotations

import argparse
import io
import os
import sys
from typing import List, Optional, Sequence

from . import __version__
from .config import load_config
from .core import Segment, all_rules, get_rule
from .engine import build_rules, exceeds, fix as apply_rule_fixes, run
from .loaders import LoaderError, apply_fixes, load
from .report import (
    github_report,
    json_report,
    rules_table,
    statistics_report,
    text_report,
)

EXTENSIONS = (".json", ".jsonl", ".ndjson", ".csv", ".tsv", ".po", ".pot", ".txt", ".md")


def _iter_paths(paths: Sequence[str]) -> List[str]:
    out: List[str] = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules"]
                for name in sorted(files):
                    if os.path.splitext(name)[1].lower() in EXTENSIONS:
                        out.append(os.path.join(root, name))
        else:
            out.append(p)
    return out


def _split(value: Optional[str]) -> Optional[List[str]]:
    if value is None:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kolint",
        description="한국어 기계번역/LLM 출력 린터 -- Korean machine-translation output linter",
    )
    parser.add_argument("--version", action="version", version="kolint %s" % __version__)
    sub = parser.add_subparsers(dest="command")

    check = sub.add_parser("check", help="파일을 검사합니다")
    check.add_argument("paths", nargs="+", help="검사할 파일 또는 디렉터리")
    check.add_argument("--select", help="적용할 규칙 (예: KO0,KO201 / all)")
    check.add_argument("--extend-select", help="기본 규칙에 추가할 규칙")
    check.add_argument("--ignore", help="제외할 규칙")
    check.add_argument("--fix", action="store_true", help="자동 수정 가능한 항목을 파일에 적용")
    check.add_argument("--diff", action="store_true", help="수정 대신 변경 예정 내용만 출력")
    check.add_argument(
        "--format", default="text", choices=("text", "json", "github", "quiet"),
        help="출력 형식",
    )
    check.add_argument("--statistics", action="store_true", help="규칙별 집계 표를 출력")
    check.add_argument(
        "--exit-level", default=None, choices=("info", "warning", "error", "never"),
        help="이 심각도 이상이 있으면 종료 코드 1 (기본: warning)",
    )
    check.add_argument("--config", help="kolint.toml 경로")
    check.add_argument("--records", help="JSON 레코드 셀렉터 (예: '[].strings[]')")
    check.add_argument("--source-key", help="원문 필드명")
    check.add_argument("--target-key", help="번역문 필드명")
    check.add_argument("--group-key", help="그룹(화자/파일) 필드명")
    check.add_argument("--no-color", action="store_true", help="색상 비활성화")

    listing = sub.add_parser("rules", help="규칙 목록을 출력합니다")
    listing.add_argument("--all", action="store_true", help="기본 비활성 규칙도 포함")

    explain = sub.add_parser("explain", help="규칙 하나를 자세히 설명합니다")
    explain.add_argument("code", help="규칙 코드 (예: KO001)")

    return parser


def _cmd_rules(args) -> int:
    rules = all_rules()
    if not args.all:
        rules = [r for r in rules if r.default_on]
    rules_table(rules)
    if not args.all:
        sys.stdout.write("\n기본 비활성 규칙까지 보려면 --all\n")
    return 0


def _cmd_explain(args) -> int:
    rule = get_rule(args.code.upper())
    if rule is None:
        sys.stderr.write("알 수 없는 규칙: %s\n" % args.code)
        return 2
    sys.stdout.write("%s  %s\n" % (rule.code, rule.name))
    sys.stdout.write("%s\n\n" % ("=" * (len(rule.code) + len(rule.name) + 2)))
    sys.stdout.write("심각도  : %s\n" % rule.severity)
    sys.stdout.write("기본값  : %s\n" % ("활성" if rule.default_on else "비활성 (opt-in)"))
    sys.stdout.write("설정필요: %s\n\n" % ("예" if rule.needs_config else "아니오"))
    sys.stdout.write("%s\n\n" % rule.summary)
    doc = (type(rule).__doc__ or "").strip()
    if doc:
        sys.stdout.write("%s\n" % doc)
    return 0


def _cmd_check(args) -> int:
    try:
        config = load_config(args.config)
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the user
        sys.stderr.write("설정 파일 오류: %s\n" % exc)
        return 2

    try:
        rules = build_rules(
            config,
            select=_split(args.select),
            ignore=_split(args.ignore),
            extend_select=_split(args.extend_select),
        )
    except ValueError as exc:
        sys.stderr.write("규칙 설정 오류: %s\n" % exc)
        return 2

    if not rules:
        sys.stderr.write("선택된 규칙이 없습니다.\n")
        return 2

    paths = _iter_paths(args.paths)
    if not paths:
        sys.stderr.write("검사할 파일이 없습니다.\n")
        return 2

    all_diagnostics = []
    total_segments = 0
    fixed_total = 0
    failures = 0

    for path in paths:
        try:
            document = load(
                path,
                records=args.records if args.records is not None else config.records,
                source_key=args.source_key or config.source_key,
                target_key=args.target_key or config.target_key,
                group_key=args.group_key or config.group_key,
            )
        except (LoaderError, ValueError, UnicodeDecodeError, OSError) as exc:
            sys.stderr.write("%s: 읽기 실패 -- %s\n" % (path, exc))
            failures += 1
            continue

        segments: List[Segment] = document.segments
        total_segments += len(segments)

        if args.fix or args.diff:
            before = [s.target for s in segments]
            n = apply_rule_fixes(segments, rules)
            if args.diff:
                for old, seg in zip(before, segments):
                    if old != seg.target:
                        sys.stdout.write("%s:%d\n- %s\n+ %s\n\n" % (path, seg.line, old, seg.target))
                for old, seg in zip(before, segments):
                    seg.target = old
                n = 0
            elif n:
                if not document.writable:
                    sys.stderr.write("%s: 이 형식은 --fix를 지원하지 않습니다\n" % path)
                    for old, seg in zip(before, segments):
                        seg.target = old
                else:
                    apply_fixes(document)
                    document.save()
                    fixed_total += n

        all_diagnostics.extend(run(segments, rules))

    if args.format == "json":
        json_report(all_diagnostics)
    elif args.format == "github":
        github_report(all_diagnostics)
    elif args.format == "text":
        text_report(all_diagnostics, color=not args.no_color)

    if args.statistics:
        statistics_report(all_diagnostics, rules, total_segments,
                          color=not args.no_color)

    if args.format != "quiet":
        summary = "%d개 세그먼트, %d개 지적" % (total_segments, len(all_diagnostics))
        if fixed_total:
            summary += ", %d개 자동 수정" % fixed_total
        sys.stderr.write("%s\n" % summary)

    if failures:
        return 2
    level = args.exit_level or config.exit_level
    if level == "never":
        return 0
    return 1 if exceeds(all_diagnostics, level) else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):  # Windows consoles default to cp949
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # pragma: no cover
            pass

    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "rules":
        return _cmd_rules(args)
    if args.command == "explain":
        return _cmd_explain(args)
    if args.command == "check":
        return _cmd_check(args)
    parser.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
