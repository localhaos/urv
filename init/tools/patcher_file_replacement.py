#!/usr/bin/env python3
"""Whole-file replacement patcher.

Supports safe replacement of a target file from stdin, an inline string, or a
source file. It is intentionally path-safe: by default all paths must remain
inside --repo.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Report:
    action: str
    path: str
    changed: bool
    bytes_before: int
    bytes_after: int
    created: bool
    dry_run: bool


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


def read_replacement(args: argparse.Namespace, repo: Path) -> bytes:
    provided = [args.content is not None, args.content_file is not None, args.stdin]
    if sum(provided) != 1:
        raise SystemExit("provide exactly one of --content, --content-file, or --stdin")
    if args.content is not None:
        data = args.content
        if args.ensure_trailing_newline and not data.endswith("\n"):
            data += "\n"
        return data.encode(args.encoding)
    if args.content_file is not None:
        source = resolve_inside(repo, args.content_file)
        if not source.exists() or not source.is_file():
            raise SystemExit(f"content file missing or not a file: {source}")
        return source.read_bytes()
    return sys.stdin.buffer.read()


def write_report(path: Path | None, report: Report) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(report), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Replace an entire file safely.")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--path", required=True, help="target path relative to --repo")
    parser.add_argument("--content")
    parser.add_argument("--content-file")
    parser.add_argument("--stdin", action="store_true")
    parser.add_argument("--encoding", default="utf-8")
    parser.add_argument("--ensure-trailing-newline", action="store_true")
    parser.add_argument("--create", action="store_true", help="allow creating a missing target")
    parser.add_argument("--mode", help="octal file mode, e.g. 0644")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    if not repo.is_dir():
        raise SystemExit(f"repo does not exist: {repo}")
    target = resolve_inside(repo, args.path)

    if not target.exists() and not args.create:
        raise SystemExit(f"target does not exist; pass --create to create it: {target}")
    if target.exists() and not target.is_file():
        raise SystemExit(f"target is not a file: {target}")

    before = target.read_bytes() if target.exists() else b""
    after = read_replacement(args, repo)
    changed = before != after
    created = not target.exists()

    if changed and not args.dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(after)
        if args.mode:
            os.chmod(target, int(args.mode, 8))

    report = Report(
        action="replace-file",
        path=str(target.relative_to(repo)),
        changed=changed,
        bytes_before=len(before),
        bytes_after=len(after),
        created=created,
        dry_run=args.dry_run,
    )
    write_report(args.report, report)
    print(json.dumps(asdict(report), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
