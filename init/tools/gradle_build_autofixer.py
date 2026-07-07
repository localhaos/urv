#!/usr/bin/env python3
"""Conservative Gradle/Kotlin build autofixer for the generated upstream tree.

The tool is intentionally conservative. It applies deterministic, idempotent fixes
for known Gradle/Android/Kotlin build issues and records unsafe compiler errors as
report-only items instead of corrupting source with regex guesses.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

DIAG_RE = re.compile(r"^(?P<kind>[ew]): file://(?P<path>.*?):(?P<line>\d+):(?P<col>\d+) (?P<msg>.*)$")

UNSAFE_MESSAGES = (
    "Unnecessary safe call",
    "Unnecessary non-null assertion",
    "Elvis operator (?:) always returns",
    "when' is exhaustive so 'else' is redundant",
    "when is exhaustive so 'else' is redundant",
    "'if' must have both main and 'else' branches when used as an expression",
    "Argument type mismatch: actual type is 'Long?', but 'Long' was expected",
    "Unresolved reference 'R'",
    "Syntax error: Expecting an element",
)

RESOURCE_DEFAULTS = {
    "bundle_update_banner_collapsed": "Updating patch bundles • %1$d out of %2$d",
    "bundle_update_banner_title": "Updating patch bundles",
    "bundle_update_progress": "%1$d/%2$d bundles processed",
    "original_revanced_manager_github": "Original ReVanced Manager GitHub",
    "selected_apps_count": "%d apps selected",
}


@dataclass
class Change:
    path: str
    rule: str
    detail: str


@dataclass
class ReportOnly:
    path: str
    line: int | None
    col: int | None
    kind: str
    message: str
    reason: str


def rel(path: Path, repo: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo.resolve()))
    except ValueError:
        return str(path)


def log(msg: str) -> None:
    print(f"[URV][gradle-autofix] {msg}", flush=True)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_if_changed(path: Path, before: str, after: str, changes: list[Change], rule: str, detail: str, repo: Path) -> bool:
    if before == after:
        return False
    path.write_text(after, encoding="utf-8")
    changes.append(Change(rel(path, repo), rule, detail))
    return True


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


def patch_kotlin_sources(repo: Path, changes: list[Change]) -> None:
    for source in sorted(repo.glob("**/*.kt")):
        if "/build/" in source.as_posix() or "/.gradle/" in source.as_posix():
            continue
        before = read(source)
        text = before

        for icon in ("Sort", "List", "OpenInNew"):
            text = patch_auto_mirrored_icon(text, icon)

        text = text.replace("consumePositionChange()", "consume()")
        text = text.replace("import androidx.compose.ui.platform.LocalLifecycleOwner\n", "import androidx.lifecycle.compose.LocalLifecycleOwner\n")
        text = text.replace("import androidx.compose.material3.Divider\n", "import androidx.compose.material3.HorizontalDivider\n")
        text = text.replace("import androidx.compose.material3.ScrollableTabRow\n", "import androidx.compose.material3.PrimaryScrollableTabRow\n")
        text = text.replace("import androidx.compose.material3.TabRow\n", "import androidx.compose.material3.PrimaryTabRow\n")
        text = re.sub(r"\bDivider\(", "HorizontalDivider(", text)
        text = re.sub(r"\bScrollableTabRow\(", "PrimaryScrollableTabRow(", text)
        text = re.sub(r"\bTabRow\(", "PrimaryTabRow(", text)
        text = text.replace("circularTrackColor", "circularIndeterminateTrackColor")

        text = text.replace(
            "if (Looper.myLooper() == null) {\n                Looper::class.java.getDeclaredMethod(\"prepareMainLooper\").invoke(null)\n            }",
            "if (Looper.myLooper() == null) {\n                Looper.prepare()\n            }",
        )
        text = text.replace("Looper.prepareMainLooper()", "Looper.prepare()")

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

        write_if_changed(source, before, text, changes, "kotlin-deterministic-fixes", "API/Compose deterministic source fixes", repo)


def patch_gradle_scripts(repo: Path, changes: list[Change]) -> None:
    props = repo / "gradle.properties"
    before = read(props) if props.exists() else ""
    text = before
    if not re.search(r"^\s*signAsDebug\s*=", text, flags=re.M):
        text += ("" if not text or text.endswith("\n") else "\n") + "signAsDebug=true\n"
    else:
        text = re.sub(r"^\s*signAsDebug\s*=.*$", "signAsDebug=true", text, count=1, flags=re.M)
    write_if_changed(props, before, text, changes, "gradle-signing", "force debug signing for CI", repo)

    root_build = repo / "build.gradle.kts"
    if root_build.exists():
        before = read(root_build)
        text = before
        marker = "LOCALHAOS_GRADLE_BUILD_AUTOFIXER"
        block = '''
// LOCALHAOS_GRADLE_BUILD_AUTOFIXER
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
        write_if_changed(root_build, before, text, changes, "gradle-kotlin-args", "add safe Kotlin compiler compatibility arg", repo)

    api_build = repo / "api/build.gradle.kts"
    if api_build.exists():
        before = read(api_build)
        text = before
        if 'singleVariant("release")' not in text:
            block = '''    publishing {
        singleVariant("release") {}
    }

'''
            if "    buildTypes {\n" in text:
                text = text.replace("    buildTypes {\n", block + "    buildTypes {\n", 1)
            elif "android {\n" in text:
                text = text.replace("android {\n", "android {\n" + block, 1)
        write_if_changed(api_build, before, text, changes, "gradle-publication", "add api singleVariant release publication", repo)

    app_build = repo / "app/build.gradle.kts"
    if app_build.exists():
        before = read(app_build)
        text = before
        text = text.replace('getFilter(com.android.build.OutputFile.ABI)', 'getFilter("ABI")')
        text = text.replace('from("$buildDir/intermediates/javac/release/classes") {', 'from(layout.buildDirectory.dir("intermediates/javac/release/classes")) {')
        text = text.replace('from("${buildDir}/intermediates/javac/release/classes") {', 'from(layout.buildDirectory.dir("intermediates/javac/release/classes")) {')
        text = re.sub(r'from\("\$buildDir/([^"]+)"\)', lambda m: f'from(layout.buildDirectory.dir("{m.group(1)}"))', text)
        text = re.sub(r'from\("\$\{buildDir\}/([^"]+)"\)', lambda m: f'from(layout.buildDirectory.dir("{m.group(1)}"))', text)
        text = re.sub(r'\bbuildDir\.resolve\("([^"]+)"\)', lambda m: f'layout.buildDirectory.dir("{m.group(1)}").get().asFile', text)
        text = re.sub(r'File\(buildDir,\s*"([^"]+)"\)', lambda m: f'layout.buildDirectory.file("{m.group(1)}").get().asFile', text)
        write_if_changed(app_build, before, text, changes, "gradle-deprecations", "replace known Gradle deprecated APIs", repo)


def patch_default_resources(repo: Path, changes: list[Change]) -> None:
    strings = repo / "app/src/main/res/values/strings.xml"
    if not strings.exists():
        return
    before = read(strings)
    text = before
    additions = []
    for name, value in RESOURCE_DEFAULTS.items():
        if f'name="{name}"' not in text:
            additions.append(f'    <string name="{name}">{value}</string>')
    if additions and "</resources>" in text:
        text = text.replace("</resources>", "\n".join(additions) + "\n</resources>", 1)
    write_if_changed(strings, before, text, changes, "resource-defaults", "add default values for localized-only strings", repo)


def parse_log(repo: Path, log_path: Path | None, report_only: list[ReportOnly]) -> None:
    if log_path is None or not log_path.exists():
        return
    for raw in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = DIAG_RE.match(raw.strip())
        if not match:
            continue
        msg = match.group("msg")
        if any(token in msg for token in UNSAFE_MESSAGES):
            path = Path(match.group("path"))
            try:
                shown_path = str(path.resolve().relative_to(repo.resolve()))
            except ValueError:
                shown_path = str(path)
            report_only.append(ReportOnly(
                path=shown_path,
                line=int(match.group("line")),
                col=int(match.group("col")),
                kind=match.group("kind"),
                message=msg,
                reason="unsafe regex source rewrite disabled; requires AST/manual fix or clean checkout rebuild",
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
    patch_gradle_scripts(repo, changes)
    patch_default_resources(repo, changes)
    patch_kotlin_sources(repo, changes)
    parse_log(repo, args.log, report_only)
    write_report(args.report, changes, report_only)

    for change in changes[:80]:
        log(f"{change.rule}: {change.path} :: {change.detail}")
    if report_only:
        log(f"report-only diagnostics: {len(report_only)}")
        for item in report_only[:40]:
            log(f"report-only: {item.path}:{item.line}:{item.col} :: {item.message}")
    if not changes and not report_only:
        log("no changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
