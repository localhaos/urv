#!/usr/bin/env python3
"""Line-oriented replacement patcher.

Supports exact text replacement, regex replacement, optional line-range limits,
required-match fail-fast behavior, and JSON reports. This tool is intended for
small deterministic edits where whole-file replacement would be too broad.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Report:
    action: str
    path: str
    changed: bool
    replacements: int
    dry_run: bool
    regex: bool
    line_start: int | None
    line_end: int | None


def resolve_inside(repo: Path, raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = repo / path
    resolved = path.resolve()
    try:
        resolved.relative_to(repo)
    except ValueError:
        raise SystemExit(f"path escapes repo: {raw}")
    return resolved


def write_report(path: Path | None, report: Report) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(report), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def in_range(line_no: int, start: int | None, end: int | None) -> bool:
    if start is not None and line_no < start:
        return False
    if end is not None and line_no > end:
        return False
    return True


def replace_lines(text: str, args: argparse.Namespace) -> tuple[str, int]:
    lines = text.splitlines(keepends=True)
    total = 0
    remaining = args.count if args.count is not None else None
    flags = 0
    if args.ignore_case:
        flags |= re.IGNORECASE
    pattern = re.compile(args.match, flags) if args.regex else None

    for idx, line in enumerate(lines):
        line_no = idx + 1
        if not in_range(line_no, args.line_start, args.line_end):
            continue
        if remaining is not None and remaining <= 0:
            break

        if args.regex:
            assert pattern is not None
            max_subs = 0 if remaining is None else remaining
            new_line, n = pattern.subn(args.replace, line, count=max_subs)
        else:
            if args.match not in line:
                continue
            max_subs = -1 if remaining is None else remaining
            if max_subs == -1:
                n = line.count(args.match)
                new_line = line.replace(args.match, args.replace)
            else:
                n = min(line.count(args.match), max_subs)
                new_line = line.replace(args.match, args.replace, max_subs)

        if n:
            lines[idx] = new_line
            total += n
            if remaining is not None:
                remaining -= n

    return "".join(lines), total


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Patch selected lines by exact or regex replacement.")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--path", required=True, help="target file path relative to --repo")
    parser.add_argument("--match", required=True)
    parser.add_argument("--replace", required=True)
    parser.add_argument("--regex", action="store_true")
    parser.add_argument("--ignore-case", action="store_true")
    parser.add_argument("--count", type=int, help="maximum replacements across selected lines")
    parser.add_argument("--line-start", type=int)
    parser.add_argument("--line-end", type=int)
    parser.add_argument("--encoding", default="utf-8")
    parser.add_argument("--require-match", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    if not repo.is_dir():
        raise SystemExit(f"repo does not exist: {repo}")
    target = resolve_inside(repo, args.path)
    if not target.exists() or not target.is_file():
        raise SystemExit(f"target missing or not a file: {target}")
    if args.count is not None and args.count < 1:
        raise SystemExit("--count must be >= 1")
    if args.line_start is not None and args.line_start < 1:
        raise SystemExit("--line-start must be >= 1")
    if args.line_end is not None and args.line_end < 1:
        raise SystemExit("--line-end must be >= 1")
    if args.line_start is not None and args.line_end is not None and args.line_end < args.line_start:
        raise SystemExit("--line-end must be >= --line-start")

    before = target.read_text(encoding=args.encoding)
    after, replacements = replace_lines(before, args)
    if args.require_match and replacements == 0:
        raise SystemExit(f"no match found in {target}")

    changed = before != after
    if changed and not args.dry_run:
        target.write_text(after, encoding=args.encoding)

    report = Report(
        action="replace-lines",
        path=str(target.relative_to(repo)),
        changed=changed,
        replacements=replacements,
        dry_run=args.dry_run,
        regex=args.regex,
        line_start=args.line_start,
        line_end=args.line_end,
    )
    write_report(args.report, report)
    print(json.dumps(asdict(report), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
