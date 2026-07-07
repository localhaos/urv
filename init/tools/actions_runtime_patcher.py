#!/usr/bin/env python3
"""Patch and validate GitHub Actions runtime refs for the bootstrap workflow.

This keeps first-party JavaScript actions on Node 24 where possible and blocks
known Node 20 refs from being reintroduced.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


REPLACEMENTS = {
    "actions/checkout@v4": "actions/checkout@v5",
    "actions/setup-java@v4": "actions/setup-java@v5",
    # actions/upload-artifact@v5 still declares node20; main currently declares node24.
    "actions/upload-artifact@v4": "actions/upload-artifact@main",
    "actions/upload-artifact@v5": "actions/upload-artifact@main",
}

FORBIDDEN = (
    "actions/checkout@v4",
    "actions/setup-java@v4",
    "actions/cache@v4",
    "actions/upload-artifact@v4",
    "actions/upload-artifact@v5",
)


@dataclass
class Change:
    path: str
    old: str
    new: str


def patch_text(path: Path, text: str) -> tuple[str, list[Change]]:
    updated = text
    changes: list[Change] = []
    for old, new in REPLACEMENTS.items():
        if old in updated:
            updated = updated.replace(old, new)
            changes.append(Change(str(path), old, new))
    return updated, changes


def patch_file(path: Path, dry_run: bool) -> tuple[str, list[Change]]:
    text = path.read_text(encoding="utf-8")
    updated, changes = patch_text(path, text)
    if updated != text and not dry_run:
        path.write_text(updated, encoding="utf-8")
    return updated, changes


def validate_text(path: Path, text: str) -> list[str]:
    problems = []
    for forbidden in FORBIDDEN:
        if forbidden in text:
            problems.append(f"{path}: forbidden Node20/legacy action ref: {forbidden}")
    if re.search(r"uses:\s*actions/cache@", text):
        problems.append(f"{path}: actions/cache is disabled because it emitted Node/punycode warnings")
    return problems


def workflow_files(repo: Path) -> list[Path]:
    root = repo / ".github/workflows"
    if not root.exists():
        return []
    return sorted([*root.glob("*.yml"), *root.glob("*.yaml")])


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    changes: list[Change] = []
    problems: list[str] = []
    for path in workflow_files(repo):
        patched_text, file_changes = patch_file(path, dry_run=args.check)
        changes.extend(file_changes)
        problems.extend(validate_text(path, patched_text))

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(
                {
                    "changes": [asdict(change) for change in changes],
                    "problems": problems,
                },
                indent=2,
                ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )

    for change in changes:
        print(f"[URV][actions-runtime] {change.path}: {change.old} -> {change.new}", flush=True)
    for problem in problems:
        print(f"[URV][actions-runtime][ERR] {problem}", file=sys.stderr, flush=True)
    return 2 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
