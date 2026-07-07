#!/usr/bin/env python3
"""Apply controlled build-time overlay files into WORK_DIR.

This is a local source/resource overlay mechanism. It does not perform runtime,
session, credential, browser, or network hijacking.

Performance notes:
- uses a cache manifest to skip already-applied template/overlay files;
- avoids reading large target files when source hash and target size match the
  previous successful application.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class Change:
    source: str
    target: str
    changed: bool
    skipped: bool
    bytes: int
    sha256: str


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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_cache(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"files": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"files": {}}
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        return {"files": {}}
    return data


def write_cache(path: Path | None, cache: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_report(path: Path | None, changes: list[Change], dry_run: bool, cache_path: Path | None) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "changed": [asdict(change) for change in changes],
        "changed_count": sum(1 for change in changes if change.changed),
        "skipped_count": sum(1 for change in changes if change.skipped),
        "file_count": len(changes),
        "dry_run": dry_run,
        "cache": str(cache_path) if cache_path else None,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def cache_hit(cache: dict[str, Any], rel_target: str, target: Path, size: int, digest: str) -> bool:
    if not target.exists() or not target.is_file():
        return False
    entry = cache.get("files", {}).get(rel_target)
    if not isinstance(entry, dict):
        return False
    if entry.get("source_sha256") != digest:
        return False
    if int(entry.get("bytes", -1)) != size:
        return False
    try:
        return target.stat().st_size == size
    except OSError:
        return False


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Apply controlled source overlay into WORK_DIR.")
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--overlay", type=Path, help="defaults to init/hijacking/overlay under repo root")
    parser.add_argument("--cache", type=Path, help="cache manifest; defaults to OUT report sibling when provided")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    repo_root = resolve_dir(args.repo_root)
    work_dir = resolve_dir(args.work_dir)
    overlay = resolve_dir(args.overlay) if args.overlay else repo_root / "init/hijacking/overlay"
    cache_path = args.cache
    if cache_path is None and args.report is not None:
        cache_path = args.report.with_suffix(".cache.json")
    if cache_path is not None and not cache_path.is_absolute():
        cache_path = (repo_root / cache_path).resolve()

    if not repo_root.is_dir():
        raise SystemExit(f"repo root missing: {repo_root}")
    if not work_dir.is_dir():
        raise SystemExit(f"work dir missing: {work_dir}")
    if overlay.exists():
        ensure_inside(repo_root, overlay)
    if cache_path is not None:
        ensure_inside(repo_root, cache_path)

    cache = load_cache(cache_path)
    files_cache = cache.setdefault("files", {})
    changes: list[Change] = []

    for source in iter_overlay_files(overlay):
        rel = source.relative_to(overlay)
        rel_target = str(rel)
        target = work_dir / rel
        ensure_inside(work_dir, target)
        size = source.stat().st_size
        digest = sha256_file(source)

        if cache_hit(cache, rel_target, target, size, digest):
            changes.append(Change(str(source.relative_to(repo_root)), rel_target, False, True, size, digest))
            continue

        data = source.read_bytes()
        before = target.read_bytes() if target.exists() and target.is_file() and target.stat().st_size == size else None
        changed = before != data
        if changed and not args.dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        if not args.dry_run:
            files_cache[rel_target] = {"source": str(source.relative_to(repo_root)), "source_sha256": digest, "bytes": size}
        changes.append(Change(str(source.relative_to(repo_root)), rel_target, changed, False, size, digest))

    if not args.dry_run:
        write_cache(cache_path, cache)
    write_report(args.report, changes, args.dry_run, cache_path)
    print(json.dumps({
        "changed_count": sum(1 for c in changes if c.changed),
        "skipped_count": sum(1 for c in changes if c.skipped),
        "file_count": len(changes),
        "dry_run": args.dry_run,
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
