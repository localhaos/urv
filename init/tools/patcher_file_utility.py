#!/usr/bin/env python3
"""Safe file utility patcher.

Operations:
- replace/copy: copy source file to destination;
- delete: remove a file or directory;
- move: move a file or directory inside the repo.

All paths are constrained to --repo by default.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Report:
    action: str
    source: str | None
    target: str | None
    changed: bool
    dry_run: bool
    detail: str


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


def rel_or_none(path: Path | None, repo: Path) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(repo))
    except ValueError:
        return str(path)


def write_report(path: Path | None, report: Report) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(report), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def paths_equal(a: Path, b: Path) -> bool:
    if not a.exists() or not b.exists() or not a.is_file() or not b.is_file():
        return False
    return a.read_bytes() == b.read_bytes()


def do_replace(repo: Path, source: Path, target: Path, args: argparse.Namespace) -> Report:
    if not source.exists() or not source.is_file():
        raise SystemExit(f"source missing or not a file: {source}")
    if target.exists() and not args.allow_overwrite:
        raise SystemExit(f"target exists; pass --allow-overwrite: {target}")
    changed = not paths_equal(source, target)
    if changed and not args.dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return Report(args.action, rel_or_none(source, repo), rel_or_none(target, repo), changed, args.dry_run, "copied source to target")


def do_delete(repo: Path, target: Path, args: argparse.Namespace) -> Report:
    if not target.exists():
        if args.missing_ok:
            return Report(args.action, None, rel_or_none(target, repo), False, args.dry_run, "target missing; skipped")
        raise SystemExit(f"target missing: {target}")
    changed = True
    if not args.dry_run:
        if target.is_dir():
            if not args.recursive:
                raise SystemExit(f"target is directory; pass --recursive: {target}")
            shutil.rmtree(target)
        else:
            target.unlink()
    return Report(args.action, None, rel_or_none(target, repo), changed, args.dry_run, "deleted target")


def do_move(repo: Path, source: Path, target: Path, args: argparse.Namespace) -> Report:
    if not source.exists():
        raise SystemExit(f"source missing: {source}")
    if target.exists() and not args.allow_overwrite:
        raise SystemExit(f"target exists; pass --allow-overwrite: {target}")
    changed = source.resolve() != target.resolve()
    if changed and not args.dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.move(str(source), str(target))
    return Report(args.action, rel_or_none(source, repo), rel_or_none(target, repo), changed, args.dry_run, "moved source to target")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Safe file utility operations for patch workflows.")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--action", required=True, choices=("replace", "copy", "delete", "move"))
    parser.add_argument("--source")
    parser.add_argument("--target", required=True)
    parser.add_argument("--allow-overwrite", action="store_true")
    parser.add_argument("--missing-ok", action="store_true")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    if not repo.is_dir():
        raise SystemExit(f"repo does not exist: {repo}")

    source = resolve_inside(repo, args.source) if args.source else None
    target = resolve_inside(repo, args.target)

    if args.action in ("replace", "copy"):
        if source is None:
            raise SystemExit(f"--source is required for {args.action}")
        report = do_replace(repo, source, target, args)
    elif args.action == "delete":
        report = do_delete(repo, target, args)
    elif args.action == "move":
        if source is None:
            raise SystemExit("--source is required for move")
        report = do_move(repo, source, target, args)
    else:
        raise SystemExit(f"unsupported action: {args.action}")

    write_report(args.report, report)
    print(json.dumps(asdict(report), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
