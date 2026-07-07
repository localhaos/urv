#!/usr/bin/env python3
"""Conservative CMake patcher for generated URV upstream trees.

Scope:
- normalize CMake SDK path hints in local.properties when the runner exposes them;
- add conservative Gradle properties useful for externalNativeBuild/CMake diagnosis;
- inspect CMakeLists.txt files and Gradle logs for CMake/Ninja/toolchain issues;
- avoid CMakeLists.txt rewrites unless a future rule is explicit and project-specific.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_CMAKE_VERSION = "3.22.1"

CMAKE_LOG_PATTERNS = (
    "CMake Error",
    "CMake Warning",
    "CMake Deprecation Warning",
    "configureCMake",
    "buildCMake",
    "externalNativeBuild",
    "CMakeFiles",
    "CMakeCache.txt",
    "CMAKE_",
    "CMAKE_MAKE_PROGRAM",
    "CMAKE_TOOLCHAIN_FILE",
    "CMAKE_ANDROID_NDK",
    "CMAKE_ANDROID_ARCH_ABI",
    "ninja:",
    "Ninja",
    "build.ninja",
    "No such file or directory",
    "Could not find",
    "not found",
    "Observed package id",
    "cmdline-tools;latest",
)

GRADLE_PROPERTIES = {
    "android.native.buildOutput": "verbose",
    "android.cmake.verbose": "true",
}


@dataclass
class Change:
    path: str
    rule: str
    detail: str


@dataclass
class Finding:
    path: str | None
    line: int | None
    message: str
    reason: str


def log(msg: str) -> None:
    print(f"[URV][cmake-patcher] {msg}", flush=True)


def rel(path: Path, repo: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo.resolve()))
    except ValueError:
        return str(path)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_if_changed(path: Path, before: str, after: str, changes: list[Change], rule: str, detail: str, repo: Path, dry_run: bool) -> None:
    if before == after:
        return
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(after, encoding="utf-8")
    changes.append(Change(rel(path, repo), rule, detail))


def set_property(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=.*$", flags=re.M)
    line = f"{key}={value}"
    if pattern.search(text):
        return pattern.sub(line, text, count=1)
    return text + ("" if not text or text.endswith("\n") else "\n") + line + "\n"


def find_android_sdk() -> Path | None:
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        value = os.environ.get(key)
        if value:
            path = Path(value)
            if path.exists():
                return path
    return None


def patch_local_properties(repo: Path, changes: list[Change], dry_run: bool) -> None:
    props = repo / "local.properties"
    before = read(props) if props.exists() else ""
    text = before

    sdk = find_android_sdk()
    if sdk:
        text = set_property(text, "sdk.dir", str(sdk))
        cmake_dir = sdk / "cmake" / DEFAULT_CMAKE_VERSION
        if cmake_dir.exists():
            text = set_property(text, "cmake.dir", str(cmake_dir))

    write_if_changed(props, before, text, changes, "cmake-local-properties", f"normalize CMake {DEFAULT_CMAKE_VERSION} path when available", repo, dry_run)


def patch_gradle_properties(repo: Path, changes: list[Change], dry_run: bool) -> None:
    props = repo / "gradle.properties"
    before = read(props) if props.exists() else ""
    text = before
    for key, value in GRADLE_PROPERTIES.items():
        text = set_property(text, key, value)
    write_if_changed(props, before, text, changes, "cmake-gradle-properties", "enable verbose native/CMake diagnostics", repo, dry_run)


def inspect_cmake_lists(repo: Path, findings: list[Finding]) -> None:
    for cmake_file in sorted(repo.glob("**/CMakeLists.txt")):
        posix = cmake_file.as_posix()
        if "/build/" in posix or "/.gradle/" in posix:
            continue
        try:
            text = read(cmake_file)
        except UnicodeDecodeError:
            findings.append(Finding(rel(cmake_file, repo), None, "CMakeLists.txt is not valid UTF-8", "manual inspection required"))
            continue
        if "cmake_minimum_required" not in text:
            findings.append(Finding(rel(cmake_file, repo), None, "missing cmake_minimum_required", "report-only; CMakeLists rewrite disabled"))
        if "project(" not in text and "project (" not in text:
            findings.append(Finding(rel(cmake_file, repo), None, "missing project() declaration", "report-only; CMakeLists rewrite disabled"))


def parse_log(log_path: Path | None, findings: list[Finding]) -> None:
    if log_path is None or not log_path.exists():
        return
    for i, line in enumerate(log_path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not any(token in line for token in CMAKE_LOG_PATTERNS):
            continue
        file_match = re.search(r"file://([^:]+):(\d+):(\d+)", line)
        findings.append(Finding(
            path=file_match.group(1) if file_match else None,
            line=i,
            message=line.strip()[:800],
            reason="CMake/Ninja diagnostic captured; CMakeLists rewrites require explicit project-specific rule",
        ))


def write_report(path: Path | None, changes: list[Change], findings: list[Finding]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "changed": [asdict(change) for change in changes],
        "findings": [asdict(finding) for finding in findings],
        "changed_count": len(changes),
        "finding_count": len(findings),
        "defaults": {
            "cmakeVersion": DEFAULT_CMAKE_VERSION,
        },
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Patch CMake path hints and report CMake/Ninja diagnostics.")
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    if not repo.is_dir():
        raise SystemExit(f"repo does not exist: {repo}")

    changes: list[Change] = []
    findings: list[Finding] = []
    patch_local_properties(repo, changes, args.dry_run)
    patch_gradle_properties(repo, changes, args.dry_run)
    inspect_cmake_lists(repo, findings)
    parse_log(args.log, findings)
    write_report(args.report, changes, findings)

    for change in changes[:40]:
        log(f"{change.rule}: {change.path} :: {change.detail}")
    if findings:
        log(f"CMake findings: {len(findings)}")
        for finding in findings[:40]:
            log(f"finding: {finding.path or '-'}:{finding.line or '-'} :: {finding.message}")
    if not changes and not findings:
        log("no changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
