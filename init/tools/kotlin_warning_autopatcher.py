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


@dataclass
class Change:
    path: str
    rule: str
    detail: str


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
    if marker not in text:
        text = text.rstrip() + "\n" + block
    write_if_changed(build, original, text, changes, "kotlin-compiler-arg", "add -Xannotation-default-target=param-property", repo)


def patch_known_deprecations(repo: Path, changes: list[Change]) -> None:
    for source in sorted(repo.glob("**/*.kt")):
        if "/build/" in source.as_posix() or "/.gradle/" in source.as_posix():
            continue
        text = read_text(source)
        original = text

        text = text.replace("Looper.prepareMainLooper()", 'if (Looper.myLooper() == null) {\n                Looper::class.java.getDeclaredMethod("prepareMainLooper").invoke(null)\n            }')
        text = text.replace("consumePositionChange()", "consume()")
        text = text.replace("Icons.Outlined.Sort", "Icons.AutoMirrored.Outlined.Sort")
        text = text.replace("Icons.Outlined.List", "Icons.AutoMirrored.Outlined.List")
        text = text.replace("Icons.Outlined.OpenInNew", "Icons.AutoMirrored.Outlined.OpenInNew")
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


def line_index(text: str, line_no: int) -> tuple[list[str], int] | None:
    lines = text.splitlines(keepends=True)
    idx = line_no - 1
    if idx < 0 or idx >= len(lines):
        return None
    return lines, idx


def replace_near(line: str, needle: str, replacement: str, col: int, radius: int = 16) -> tuple[str, bool]:
    start = max(0, col - radius - 1)
    end = min(len(line), col + radius - 1)
    pos = line.find(needle, start, end)
    if pos < 0:
        pos = line.find(needle)
    if pos < 0:
        return line, False
    return line[:pos] + replacement + line[pos + len(needle):], True


def remove_simple_elvis(line: str, col: int) -> tuple[str, bool]:
    pos = line.find("?:", max(0, col - 12))
    if pos < 0:
        pos = line.find("?:")
    if pos < 0:
        return line, False
    tail = line[pos:]
    if any(token in tail for token in ["{", "}", "->"]):
        return line, False
    patched = line[:pos].rstrip() + "\n"
    return patched, True


def apply_log_warning(repo: Path, path: Path, line_no: int, col: int, msg: str, changes: list[Change]) -> None:
    if not path.exists() or path.suffix != ".kt":
        return
    text = read_text(path)
    item = line_index(text, line_no)
    if item is None:
        return
    lines, idx = item
    line = lines[idx]
    patched = line
    ok = False
    rule = ""

    if "Unnecessary safe call" in msg:
        patched, ok = replace_near(line, "?.", ".", col)
        rule = "remove-unnecessary-safe-call"
    elif "Unnecessary non-null assertion" in msg:
        patched, ok = replace_near(line, "!!", "", col)
        rule = "remove-unnecessary-non-null-assertion"
    elif "Elvis operator (?:) always returns" in msg:
        patched, ok = remove_simple_elvis(line, col)
        rule = "remove-redundant-elvis"
    elif "No cast needed" in msg:
        patched = re.sub(r"\s+as\??\s+[A-Za-z0-9_.<>?]+", "", line, count=1)
        ok = patched != line
        rule = "remove-redundant-cast"
    elif "when' is exhaustive so 'else' is redundant" in msg or "when is exhaustive so 'else' is redundant" in msg:
        patched = re.sub(r"\s*else\s*->.*", "", line)
        ok = patched != line
        rule = "remove-redundant-when-else"
    else:
        return

    if not ok:
        return
    lines[idx] = patched
    after = "".join(lines)
    write_if_changed(path, text, after, changes, rule, msg, repo)


def apply_log_driven_rules(repo: Path, log_path: Path | None, changes: list[Change]) -> None:
    if log_path is None or not log_path.exists():
        return
    for raw in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = WARN_RE.match(raw.strip())
        if not match:
            continue
        path = Path(match.group("path"))
        if not path.is_absolute():
            continue
        try:
            rel = path.resolve().relative_to(repo)
        except ValueError:
            continue
        apply_log_warning(repo, repo / rel, int(match.group("line")), int(match.group("col")), match.group("msg"), changes)


def write_report(path: Path | None, changes: list[Change]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(change) for change in changes], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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
    ensure_kotlin_annotation_default_target(repo, changes)
    patch_known_deprecations(repo, changes)
    apply_log_driven_rules(repo, args.log, changes)
    write_report(args.report, changes)

    if changes:
        log(f"changed {len(changes)} item(s)")
        for change in changes[:40]:
            log(f"{change.rule}: {change.path} :: {change.detail}")
    else:
        log("no changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
