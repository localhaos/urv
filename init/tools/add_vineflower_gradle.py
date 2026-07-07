#!/usr/bin/env python3
"""Add Vineflower to a Gradle Android project through the version catalog."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


class VineflowerPatchError(RuntimeError):
    pass


def log(message: str) -> None:
    print(f"[URV][vineflower] {message}", flush=True)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_if_changed(path: Path, before: str, after: str) -> None:
    if after != before:
        path.write_text(after, encoding="utf-8")
        log(f"patched {path}")
    else:
        log(f"unchanged {path}")


def find_required(repo: Path, candidates: list[str]) -> Path:
    for candidate in candidates:
        path = repo / candidate
        if path.exists():
            return path
    raise VineflowerPatchError("missing required file: " + " or ".join(candidates))


def patch_version_catalog(repo: Path, version: str) -> None:
    catalog = find_required(repo, ["gradle/libs.versions.toml"])
    text = read(catalog)
    original = text

    if "\nvineflower = " not in text:
        version_line = f'vineflower = "{version}"\n'
        anchor = re.search(r'(?m)^bouncycastle\s*=\s*"[^"]+"\s*$', text)
        if anchor:
            insert_at = anchor.end()
            text = text[:insert_at] + "\n" + version_line.rstrip("\n") + text[insert_at:]
        else:
            marker = "\n[libraries]\n"
            if marker not in text:
                raise VineflowerPatchError("version catalog has no [libraries] section")
            text = text.replace(marker, "\n" + version_line + marker.lstrip("\n"), 1)
    else:
        text = re.sub(
            r'(?m)^vineflower\s*=\s*"[^"]+"\s*$',
            f'vineflower = "{version}"',
            text,
            count=1,
        )

    library_line = 'vineflower = { group = "org.vineflower", name = "vineflower", version.ref = "vineflower" }'
    if library_line not in text and not re.search(r'(?m)^vineflower\s*=\s*\{[^\n]*org\.vineflower[^\n]*\}\s*$', text):
        bcprov = re.search(r'(?m)^bcprov\s*=\s*\{[^\n]+\}\s*$', text)
        if bcprov:
            insert_at = bcprov.end()
            text = text[:insert_at] + "\n" + library_line + text[insert_at:]
        else:
            plugins_marker = "\n[plugins]\n"
            if plugins_marker not in text:
                raise VineflowerPatchError("version catalog has no [plugins] section")
            text = text.replace(plugins_marker, "\n# JVM decompiler\n" + library_line + "\n" + plugins_marker.lstrip("\n"), 1)

    write_if_changed(catalog, original, text)


def patch_app_build(repo: Path) -> None:
    build = find_required(repo, ["app/build.gradle.kts", "app/build.gradle"])
    text = read(build)
    original = text

    if "libs.vineflower" in text or "org.vineflower:vineflower" in text:
        write_if_changed(build, original, text)
        return

    dependency_block = '''
    // JVM decompiler
    implementation(libs.vineflower)
'''

    anchors = [
        "    // Downloader plugins\n",
        "    // Native processes\n",
        "}\n\nbuildscript {\n",
    ]
    for anchor in anchors:
        if anchor in text:
            text = text.replace(anchor, dependency_block + "\n" + anchor, 1)
            break
    else:
        raise VineflowerPatchError("cannot find stable dependency insertion anchor in app build file")

    write_if_changed(build, original, text)


def patch_repository(repo: Path, version: str) -> None:
    patch_version_catalog(repo, version)
    patch_app_build(repo)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Add Vineflower through Gradle version catalog.")
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--version", default="1.12.0")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    if not repo.is_dir():
        raise VineflowerPatchError(f"repo path does not exist: {repo}")

    version = args.version.strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9_.-]+)?", version):
        raise VineflowerPatchError(f"invalid Vineflower version: {version!r}")

    patch_repository(repo, version)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except VineflowerPatchError as exc:
        print(f"[URV][vineflower][ERR] {exc}", file=sys.stderr, flush=True)
        raise SystemExit(2)
