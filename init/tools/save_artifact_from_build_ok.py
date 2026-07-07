#!/usr/bin/env python3
"""Download GitHub Actions artifacts listed in a build_ok file.

Accepted build_ok formats:
- one raw numeric artifact id per line;
- artifact_id=123;
- artifact:123;
- JSON list/object containing artifact ids.

Downloaded ZIP files are stored under --out-dir and described in a JSON manifest.
The downloader supports parallel execution and skip-existing to avoid repeatedly
waiting on unchanged template/artifact ZIPs.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ID_RE = re.compile(r"(?:artifact(?:_id)?\s*[:=]\s*)?(?P<id>\d{3,})")


@dataclass
class SavedArtifact:
    artifact_id: int
    path: str | None
    bytes_written: int
    status: str
    error: str | None = None


@dataclass
class Manifest:
    repository: str
    build_ok: str
    out_dir: str
    parallel: int
    timeout_seconds: int
    saved: list[SavedArtifact]


def log(message: str) -> None:
    print(f"[URV][build-ok-artifact] {message}", flush=True)


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


def collect_ids_from_json(value: Any, result: set[int]) -> None:
    if isinstance(value, int):
        if value >= 100:
            result.add(value)
    elif isinstance(value, str):
        for match in ID_RE.finditer(value):
            result.add(int(match.group("id")))
    elif isinstance(value, list):
        for item in value:
            collect_ids_from_json(item, result)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in {"artifact", "artifact_id", "artifactId", "id"}:
                collect_ids_from_json(item, result)
            elif isinstance(item, (dict, list, str, int)):
                collect_ids_from_json(item, result)


def parse_build_ok(path: Path) -> list[int]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []

    result: set[int] = set()
    if text.startswith("{") or text.startswith("["):
        try:
            collect_ids_from_json(json.loads(text), result)
        except Exception:
            pass

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        for match in ID_RE.finditer(line):
            result.add(int(match.group("id")))
    return sorted(result)


def request_with_redirect(url: str, token: str, accept: str = "application/vnd.github+json") -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "localhaos-urv-build-ok-artifact-saver",
        },
    )


def download_artifact_zip(
    repository: str,
    artifact_id: int,
    token: str,
    out_dir: Path,
    retries: int,
    timeout_seconds: int,
    skip_existing: bool,
) -> SavedArtifact:
    url = f"https://api.github.com/repos/{repository}/actions/artifacts/{artifact_id}/zip"
    out_path = out_dir / f"artifact-{artifact_id}.zip"
    last_error: str | None = None

    if skip_existing and out_path.exists() and out_path.is_file() and out_path.stat().st_size > 0:
        return SavedArtifact(artifact_id, str(out_path), out_path.stat().st_size, "cached")

    for attempt in range(1, retries + 1):
        try:
            req = request_with_redirect(url, token, accept="application/vnd.github+json")
            with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
                data = response.read()
            out_dir.mkdir(parents=True, exist_ok=True)
            tmp = out_path.with_suffix(out_path.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(out_path)
            return SavedArtifact(artifact_id, str(out_path), len(data), "saved")
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}: {exc.reason}"
            if exc.code in {404, 410}:
                return SavedArtifact(artifact_id, None, 0, "missing", last_error)
        except Exception as exc:
            last_error = repr(exc)
        if attempt < retries:
            time.sleep(min(10, 2 * attempt))

    return SavedArtifact(artifact_id, None, 0, "failed", last_error)


def write_manifest(path: Path, manifest: Manifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(manifest), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Download artifact IDs listed in build_ok into out/saved-artifacts.")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--build-ok", default="build_ok")
    parser.add_argument("--out-dir", default="out/saved-artifacts")
    parser.add_argument("--manifest", default="out/saved-artifacts/manifest.json")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=35, help="per-request timeout in seconds")
    parser.add_argument("--parallel", type=int, default=4, help="parallel download workers")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    if not repo.is_dir():
        raise SystemExit(f"repo does not exist: {repo}")
    if not args.repository:
        raise SystemExit("missing --repository or GITHUB_REPOSITORY")
    if not args.token:
        raise SystemExit("missing --token or GITHUB_TOKEN")
    if args.retries < 1:
        raise SystemExit("--retries must be >= 1")
    if args.timeout < 5:
        raise SystemExit("--timeout must be >= 5")
    if args.parallel < 1:
        raise SystemExit("--parallel must be >= 1")

    build_ok = resolve_inside(repo, args.build_ok)
    out_dir = resolve_inside(repo, args.out_dir)
    manifest_path = resolve_inside(repo, args.manifest)

    ids = parse_build_ok(build_ok)
    if not ids:
        manifest = Manifest(args.repository, str(build_ok.relative_to(repo)), str(out_dir.relative_to(repo)), args.parallel, args.timeout, [])
        write_manifest(manifest_path, manifest)
        log("no artifact ids in build_ok")
        return 0

    log(f"artifact ids from build_ok: {', '.join(map(str, ids))}")
    workers = min(args.parallel, len(ids))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                download_artifact_zip,
                args.repository,
                artifact_id,
                args.token,
                out_dir,
                args.retries,
                args.timeout,
                args.skip_existing,
            )
            for artifact_id in ids
        ]
        saved = [future.result() for future in futures]

    saved.sort(key=lambda item: item.artifact_id)
    manifest = Manifest(args.repository, str(build_ok.relative_to(repo)), str(out_dir.relative_to(repo)), args.parallel, args.timeout, saved)
    write_manifest(manifest_path, manifest)

    for item in saved:
        if item.status in {"saved", "cached"}:
            log(f"{item.status} artifact {item.artifact_id}: {item.path} ({item.bytes_written} bytes)")
        else:
            log(f"{item.status} artifact {item.artifact_id}: {item.error}")

    if args.fail_on_error and any(item.status not in {"saved", "cached"} for item in saved):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
