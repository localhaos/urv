#!/usr/bin/env python3
"""Apply conservative source/Gradle rewrites for recurring Kotlin/Android warnings."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


WARN_RE = re.compile(r"^w: file://(?P<path>.*?):(?P<line>\d+):(?P<col>\d+) (?P<msg>.*)$")

REPORT_ONLY_WARNING_PARTS = (
    "Unnecessary safe call",
    "Unnecessary non-null assertion",
    "Elvis operator (?:) always returns",
    "when' is exhaustive so 'else' is redundant",
    "when is exhaustive so 'else' is redundant",
)


@dataclass
class Change:
    path: str
    rule: str
    detail: str


@dataclass
class ReportOnly:
    path: str
    line: int
    col: int
    message: str
    reason: str


def log(message: str) -> None:
    print(f"[URV][warning-autopatch] {message}", flush=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_if_changed(path: Path, before: str, after: str, changes: list[Change], rule: str, detail: str, repo: Path) -> bool:
    if after == before:
        return False
    path.write_text(after, encoding="utf-8")
    changes.append(Change(str(path.relative_to(repo)), rule, detail))
    return True


def ensure_kotlin_annotation_default_target(repo: Path, changes: list[Change]) -> None:
    build = repo / "build.gradle.kts"
    if not build.exists():
        return
    text = read_text(build)
    original = text
    marker = "LOCALHAOS_KOTLIN_WARNING_AUTOPATCH"
    block = '''
// LOCALHAOS_KOTLIN_WARNING_AUTOPATCH
subprojects {
    tasks.withType<org.jetbrains.kotlin.gradle.tasks.KotlinCompile>().configureEach {
        compilerOptions {
            freeCompilerArgs.add("-Xannotation-default-target=param-property")
        }
    }
}
'''
    if marker not in text and "-Xannotation-default-target=param-property" not in text:
        text = text.rstrip() + "\n" + block
    write_if_changed(build, original, text, changes, "kotlin-compiler-arg", "add -Xannotation-default-target=param-property", repo)


def ensure_import(text: str, import_line: str) -> str:
    if import_line in text:
        return text
    anchor = "import androidx.compose.material.icons.Icons\n"
    if anchor in text:
        return text.replace(anchor, anchor + import_line, 1)
    package_match = re.search(r"^(package\s+[^\n]+\n)", text, flags=re.M)
    if package_match:
        end = package_match.end(1)
        return text[:end] + "\n" + import_line + text[end:]
    return import_line + text


def patch_auto_mirrored_icon(text: str, name: str) -> str:
    old_symbol = f"Icons.Outlined.{name}"
    new_symbol = f"Icons.AutoMirrored.Outlined.{name}"
    old_import = f"import androidx.compose.material.icons.outlined.{name}\n"
    new_import = f"import androidx.compose.material.icons.automirrored.outlined.{name}\n"

    if old_symbol in text:
        text = text.replace(old_symbol, new_symbol)
    if new_symbol in text:
        text = text.replace(old_import, "")
        text = ensure_import(text, new_import)
    return text


def patch_known_deprecations(repo: Path, changes: list[Change]) -> None:
    for source in sorted(repo.glob("**/*.kt")):
        if "/build/" in source.as_posix() or "/.gradle/" in source.as_posix():
            continue
        text = read_text(source)
        original = text

        text = text.replace("Looper.prepareMainLooper()", "Looper.prepare()")
        text = text.replace("consumePositionChange()", "consume()")
        for icon_name in ("Sort", "List", "OpenInNew"):
            text = patch_auto_mirrored_icon(text, icon_name)
        text = re.sub(r"\bDivider\(", "HorizontalDivider(", text)
        text = re.sub(r"\bScrollableTabRow\(", "PrimaryScrollableTabRow(", text)
        text = re.sub(r"\bTabRow\(", "PrimaryTabRow(", text)
        text = re.sub(r"ButtonDefaults\.outlinedButtonBorder(?!\s*\()", "ButtonDefaults.outlinedButtonBorder(enabled = true)", text)
        text = text.replace("circularTrackColor", "circularIndeterminateTrackColor")
        text = text.replace("import androidx.compose.material3.Divider\n", "import androidx.compose.material3.HorizontalDivider\n")
        text = text.replace("import androidx.compose.material3.ScrollableTabRow\n", "import androidx.compose.material3.PrimaryScrollableTabRow\n")
        text = text.replace("import androidx.compose.material3.TabRow\n", "import androidx.compose.material3.PrimaryTabRow\n")
        text = text.replace("import androidx.compose.ui.platform.LocalLifecycleOwner\n", "import androidx.lifecycle.compose.LocalLifecycleOwner\n")

        if "getParcelableExtra<Parameters>(KEY)" in text and "getParcelableExtra(KEY, Parameters::class.java)" not in text:
            if "import android.os.Build\n" not in text:
                text = text.replace("import android.os.Bundle\n", "import android.os.Build\nimport android.os.Bundle\n", 1)
            text = text.replace(
                "        val params = intent.getParcelableExtra<Parameters>(KEY)!!\n",
                '''        val params = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            intent.getParcelableExtra(KEY, Parameters::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra(KEY) as? Parameters
        }!!
''',
            )

        write_if_changed(source, original, text, changes, "known-kotlin-deprecations", "known API/Compose substitutions", repo)


def apply_log_driven_rules(repo: Path, log_path: Path | None, report_only: list[ReportOnly]) -> None:
    if log_path is None or not log_path.exists():
        return
    for raw in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = WARN_RE.match(raw.strip())
        if not match:
            continue
        msg = match.group("msg")
        if not any(part in msg for part in REPORT_ONLY_WARNING_PARTS):
            continue
        path = Path(match.group("path"))
        if not path.is_absolute():
            continue
        try:
            rel = path.resolve().relative_to(repo)
            display_path = str(rel)
        except ValueError:
            display_path = str(path)
        report_only.append(ReportOnly(
            path=display_path,
            line=int(match.group("line")),
            col=int(match.group("col")),
            message=msg,
            reason="generic nullable/syntax rewrite disabled; requires AST-safe/manual fix",
        ))


def write_report(path: Path | None, changes: list[Change], report_only: list[ReportOnly]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "changed": [asdict(change) for change in changes],
        "report_only": [asdict(item) for item in report_only],
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    if not repo.is_dir():
        raise SystemExit(f"repo does not exist: {repo}")

    changes: list[Change] = []
    report_only: list[ReportOnly] = []
    ensure_kotlin_annotation_default_target(repo, changes)
    patch_known_deprecations(repo, changes)
    apply_log_driven_rules(repo, args.log, report_only)
    write_report(args.report, changes, report_only)

    if changes:
        log(f"changed {len(changes)} item(s)")
        for change in changes[:40]:
            log(f"{change.rule}: {change.path} :: {change.detail}")
    if report_only:
        log(f"report-only warnings: {len(report_only)}")
        for item in report_only[:40]:
            log(f"report-only: {item.path}:{item.line}:{item.col} :: {item.message}")
    if not changes and not report_only:
        log("no changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
