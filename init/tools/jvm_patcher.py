#!/usr/bin/env python3
"""Conservative JVM/Gradle runtime patcher for generated URV upstream trees.

Scope:
- normalize Gradle/Kotlin daemon JVM arguments;
- force UTF-8 file encoding;
- align Java/Kotlin compilation to JVM 17;
- report JVM-related build failures from Gradle logs.

This tool does not rewrite Kotlin expressions. It is runtime/build-environment
focused, not a source semantics fixer.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

JVM_LOG_PATTERNS = (
    "OutOfMemoryError",
    "Java heap space",
    "GC overhead limit exceeded",
    "Metaspace",
    "Gradle build daemon disappeared",
    "Kotlin daemon",
    "Could not determine java version",
    "Unsupported class file major version",
    "Inconsistent JVM-target compatibility",
    "Cannot inline bytecode built with JVM target",
    "source release",
    "target release",
)

GRADLE_PROPERTIES = {
    "org.gradle.jvmargs": "-Xmx4096m -XX:MaxMetaspaceSize=1024m -Dfile.encoding=UTF-8 -XX:+UseParallelGC",
    "kotlin.daemon.jvmargs": "-Xmx3072m -Dfile.encoding=UTF-8",
    "org.gradle.daemon": "true",
    "org.gradle.parallel": "true",
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
    print(f"[URV][jvm-patcher] {msg}", flush=True)


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


def patch_gradle_properties(repo: Path, changes: list[Change], dry_run: bool) -> None:
    props = repo / "gradle.properties"
    before = read(props) if props.exists() else ""
    text = before
    for key, value in GRADLE_PROPERTIES.items():
        text = set_property(text, key, value)
    write_if_changed(props, before, text, changes, "jvm-gradle-properties", "normalize Gradle/Kotlin daemon JVM properties", repo, dry_run)


def patch_root_build(repo: Path, changes: list[Change], dry_run: bool) -> None:
    build = repo / "build.gradle.kts"
    if not build.exists():
        return
    before = read(build)
    text = before
    marker = "LOCALHAOS_JVM_PATCHER"
    block = '''
// LOCALHAOS_JVM_PATCHER
subprojects {
    plugins.withId("java") {
        extensions.configure<org.gradle.api.plugins.JavaPluginExtension> {
            toolchain.languageVersion.set(org.gradle.jvm.toolchain.JavaLanguageVersion.of(17))
        }
    }

    tasks.withType<org.gradle.api.tasks.compile.JavaCompile>().configureEach {
        sourceCompatibility = org.gradle.api.JavaVersion.VERSION_17.toString()
        targetCompatibility = org.gradle.api.JavaVersion.VERSION_17.toString()
        options.encoding = "UTF-8"
    }

    tasks.withType<org.jetbrains.kotlin.gradle.tasks.KotlinCompile>().configureEach {
        compilerOptions {
            jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        }
    }
}
'''
    if marker not in text and "JvmTarget.JVM_17" not in text:
        text = text.rstrip() + "\n" + block
    write_if_changed(build, before, text, changes, "jvm-build-script", "align Java/Kotlin JVM target to 17", repo, dry_run)


def parse_log(log_path: Path | None, findings: list[Finding]) -> None:
    if log_path is None or not log_path.exists():
        return
    for i, line in enumerate(log_path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not any(token in line for token in JVM_LOG_PATTERNS):
            continue
        file_match = re.search(r"file://([^:]+):(\d+):(\d+)", line)
        findings.append(Finding(
            path=file_match.group(1) if file_match else None,
            line=i,
            message=line.strip()[:600],
            reason="JVM/Gradle runtime diagnostic captured; source expression rewrites are intentionally out of scope",
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
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Patch JVM/Gradle runtime settings in a generated upstream tree.")
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
    patch_gradle_properties(repo, changes, args.dry_run)
    patch_root_build(repo, changes, args.dry_run)
    parse_log(args.log, findings)
    write_report(args.report, changes, findings)

    for change in changes[:40]:
        log(f"{change.rule}: {change.path} :: {change.detail}")
    if findings:
        log(f"JVM findings: {len(findings)}")
        for finding in findings[:40]:
            log(f"finding: line {finding.line} :: {finding.message}")
    if not changes and not findings:
        log("no changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
