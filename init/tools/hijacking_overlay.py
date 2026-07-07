#!/usr/bin/env python3
"""Apply controlled build-time overlay files into WORK_DIR.

This is a local source/resource overlay mechanism. It does not perform runtime,
session, credential, browser, or network hijacking.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Change:
    source: str
    target: str
    changed: bool
    bytes: int


def resolve_dir(path: Path) -> Path:
    return path.resolve()


def ensure_inside(root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        raise SystemExit(f"path escapes root: {path}")


def iter_overlay_files(overlay: Path) -> list[Path]:
    if not overlay.exists():
        return []
    return sorted(p for p in overlay.rglob("*") if p.is_file() and p.name != ".gitkeep")


def write_report(path: Path | None, changes: list[Change], dry_run: bool) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "changed": [asdict(change) for change in changes],
        "changed_count": sum(1 for change in changes if change.changed),
        "file_count": len(changes),
        "dry_run": dry_run,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Apply controlled source overlay into WORK_DIR.")
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--overlay", type=Path, help="defaults to init/hijacking/overlay under repo root")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    repo_root = resolve_dir(args.repo_root)
    work_dir = resolve_dir(args.work_dir)
    overlay = resolve_dir(args.overlay) if args.overlay else repo_root / "init/hijacking/overlay"

    if not repo_root.is_dir():
        raise SystemExit(f"repo root missing: {repo_root}")
    if not work_dir.is_dir():
        raise SystemExit(f"work dir missing: {work_dir}")
    if overlay.exists():
        ensure_inside(repo_root, overlay)

    changes: list[Change] = []
    for source in iter_overlay_files(overlay):
        rel = source.relative_to(overlay)
        target = work_dir / rel
        ensure_inside(work_dir, target)
        data = source.read_bytes()
        before = target.read_bytes() if target.exists() and target.is_file() else None
        changed = before != data
        if changed and not args.dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        changes.append(Change(str(source.relative_to(repo_root)), str(target.relative_to(work_dir)), changed, len(data)))

    write_report(args.report, changes, args.dry_run)
    print(json.dumps({"changed_count": sum(1 for c in changes if c.changed), "file_count": len(changes), "dry_run": args.dry_run}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
