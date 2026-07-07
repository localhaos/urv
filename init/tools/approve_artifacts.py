#!/usr/bin/env python3
"""Write an artifact approval manifest used by staged resume."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Approve existing build artifacts for staged resume.")
    parser.add_argument("--out-dir", type=Path, default=Path("out"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--note", default="approved by user")
    parser.add_argument("--artifact", action="append", default=[], help="artifact path to hash; may be repeated")
    args = parser.parse_args()

    out_dir = args.out_dir.resolve()
    manifest = args.manifest.resolve() if args.manifest else out_dir / "approved-artifacts.env"
    manifest.parent.mkdir(parents=True, exist_ok=True)

    artifacts = []
    for raw in args.artifact:
        path = Path(raw).resolve()
        if not path.exists() or not path.is_file():
            raise SystemExit(f"artifact missing or not a file: {path}")
        artifacts.append({"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size})

    json_manifest = manifest.with_suffix(".json")
    json_manifest.write_text(json.dumps({
        "approved": True,
        "timestamp_unix": int(time.time()),
        "note": args.note,
        "artifacts": artifacts,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    manifest.write_text(
        "APPROVED=1\n"
        f"APPROVED_AT_UNIX={int(time.time())}\n"
        f"APPROVAL_NOTE={args.note}\n"
        f"APPROVAL_JSON={json_manifest}\n",
        encoding="utf-8",
    )
    print(f"approved manifest written: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
