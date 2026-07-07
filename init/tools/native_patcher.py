#!/usr/bin/env python3
"""Conservative Android native/NDK/CMake patcher for generated URV upstream trees.

Scope:
- normalize native build environment declarations in local.properties;
- remove deprecated ndk.dir from local.properties;
- pin android.ndkVersion in Android modules;
- add conservative Gradle properties for Android native/CMake diagnostics;
- report NDK/CMake/linker diagnostics from Gradle logs;
- avoid Kotlin/Java source rewrites.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

NATIVE_LOG_PATTERNS = (
    "[CXX5106]",
    "NDK was located by using ndk.dir property",
    "ndk.dir",
    "android.ndkVersion",
    "CMake Error",
    "CMake Warning",
    "ninja:",
    "ld.lld:",
    "clang:",
    "clang++:",
    "externalNativeBuild",
    "configureCMake",
    "buildCMake",
    "CXX",
    "NDK",
    "ANDROID_NDK",
    "ANDROID_NDK_HOME",
    "ANDROID_NDK_ROOT",
    "CMAKE_MAKE_PROGRAM",
    "Observed package id",
    "cmdline-tools;latest",
    "ABI",
    "arm64-v8a",
    "armeabi-v7a",
    "x86_64",
)

GRADLE_PROPERTIES = {
    "android.injected.build.abi": "arm64-v8a",
    "android.native.disableCompilerDaemon": "true",
    "android.native.buildOutput": "verbose",
}

DEFAULT_NDK_VERSION = "25.2.9519653"
DEFAULT_CMAKE_VERSION = "3.22.1"


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
    print(f"[URV][native-patcher] {msg}", flush=True)


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


def remove_property(text: str, key: str) -> str:
    text = re.sub(rf"^\s*{re.escape(key)}\s*=.*(?:\n|$)", "", text, flags=re.M)
    return text


def find_android_sdk() -> Path | None:
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        value = os.environ.get(key)
        if value:
            path = Path(value)
            if path.exists():
                return path
    return None


def patch_local_properties(repo: Path, changes: list[Change], dry_run: bool) -> None:
    local_props = repo / "local.properties"
    before = read(local_props) if local_props.exists() else ""
    text = before

    # CXX5106: ndk.dir is deprecated. Keep NDK selection in Gradle via android.ndkVersion.
    text = remove_property(text, "ndk.dir")

    sdk = find_android_sdk()
    if sdk:
        text = set_property(text, "sdk.dir", str(sdk))
        cmake_dir = sdk / "cmake" / DEFAULT_CMAKE_VERSION
        if cmake_dir.exists():
            text = set_property(text, "cmake.dir", str(cmake_dir))

    write_if_changed(local_props, before, text, changes, "native-local-properties", "remove deprecated ndk.dir and normalize sdk/cmake paths", repo, dry_run)


def patch_gradle_properties(repo: Path, changes: list[Change], dry_run: bool) -> None:
    props = repo / "gradle.properties"
    before = read(props) if props.exists() else ""
    text = before
    for key, value in GRADLE_PROPERTIES.items():
        text = set_property(text, key, value)
    write_if_changed(props, before, text, changes, "native-gradle-properties", "add conservative native build Gradle properties", repo, dry_run)


def is_android_build_script(text: str) -> bool:
    return (
        "com.android.application" in text
        or "com.android.library" in text
        or "com.android.dynamic-feature" in text
        or re.search(r"^\s*android\s*\{", text, flags=re.M) is not None
    )


def has_native_signal(text: str) -> bool:
    return (
        "externalNativeBuild" in text
        or "CMakeLists.txt" in text
        or "cmake" in text
        or "ndkVersion" in text
        or "ndk {" in text
        or "abiFilters" in text
    )


def patch_kotlin_dsl_ndk_version(text: str) -> str:
    if "ndkVersion" in text:
        return text
    return text.replace("android {\n", f"android {{\n    ndkVersion = \"{DEFAULT_NDK_VERSION}\"\n", 1)


def patch_groovy_dsl_ndk_version(text: str) -> str:
    if "ndkVersion" in text:
        return text
    return text.replace("android {\n", f"android {{\n    ndkVersion \"{DEFAULT_NDK_VERSION}\"\n", 1)


def patch_android_module_ndk_versions(repo: Path, changes: list[Change], dry_run: bool) -> None:
    candidates = list(repo.glob("**/build.gradle.kts")) + list(repo.glob("**/build.gradle"))
    for build in sorted(candidates):
        posix = build.as_posix()
        if "/build/" in posix or "/.gradle/" in posix or "/.cxx/" in posix:
            continue
        before = read(build)
        if not is_android_build_script(before):
            continue

        text = before
        if build.name.endswith(".kts"):
            text = patch_kotlin_dsl_ndk_version(text)
        else:
            text = patch_groovy_dsl_ndk_version(text)

        detail = f"pin android.ndkVersion {DEFAULT_NDK_VERSION}"
        if has_native_signal(before):
            detail += " for native Android module"
        else:
            detail += " for Android module to avoid ndk.dir fallback"
        write_if_changed(build, before, text, changes, "native-gradle-android", detail, repo, dry_run)


def parse_log(log_path: Path | None, findings: list[Finding]) -> None:
    if log_path is None or not log_path.exists():
        return
    for i, line in enumerate(log_path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not any(token in line for token in NATIVE_LOG_PATTERNS):
            continue
        file_match = re.search(r"file://([^:]+):(\d+):(\d+)", line)
        reason = "native/NDK/CMake diagnostic captured; source and CMakeLists rewrites require explicit project-specific rule"
        if "[CXX5106]" in line or "ndk.dir" in line:
            reason = f"CXX5106 handled by removing ndk.dir and pinning android.ndkVersion {DEFAULT_NDK_VERSION}"
        findings.append(Finding(
            path=file_match.group(1) if file_match else None,
            line=i,
            message=line.strip()[:700],
            reason=reason,
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
            "ndkVersion": DEFAULT_NDK_VERSION,
            "cmakeVersion": DEFAULT_CMAKE_VERSION,
            "deprecatedLocalProperties": ["ndk.dir"],
        },
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Patch Android native/NDK/CMake build environment in a generated upstream tree.")
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
    patch_android_module_ndk_versions(repo, changes, args.dry_run)
    parse_log(args.log, findings)
    write_report(args.report, changes, findings)

    for change in changes[:80]:
        log(f"{change.rule}: {change.path} :: {change.detail}")
    if findings:
        log(f"native findings: {len(findings)}")
        for finding in findings[:40]:
            log(f"finding: line {finding.line} :: {finding.message}")
    if not changes and not findings:
        log("no changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
