#!/usr/bin/env python3
"""Import safe build ideas from localhaos/revanced-manager into URV upstream.

This tool treats the idea repository as a reference only. It does not blindly
copy source files. The applied modification is a guarded Gradle patch that
bundles downloader API artifacts and an optional runtime plugin into the final
manager APK assets.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MARKER = "LOCALHAOS_ONE_APK_BUNDLE"
DEFAULT_IDEA_REPO = "https://github.com/localhaos/revanced-manager.git"
DEFAULT_IDEA_REF = "main"


@dataclass
class Change:
    path: str
    rule: str
    detail: str


@dataclass
class Idea:
    name: str
    present: bool
    source: str | None
    note: str


def log(msg: str) -> None:
    print(f"[URV][localhaos-ideas] {msg}", flush=True)


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_if_changed(path: Path, before: str, after: str, changes: list[Change], rule: str, detail: str, repo: Path, dry_run: bool) -> None:
    if before == after:
        return
    if not dry_run:
        path.write_text(after, encoding="utf-8")
    changes.append(Change(rel(path, repo), rule, detail))


def clone_idea_repo(repo_url: str, ref: str, dest: Path, timeout: int) -> bool:
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", "--depth", "1", "--branch", ref, repo_url, str(dest)]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        return True
    except Exception as exc:
        log(f"idea clone skipped/failed: {exc!r}")
        return False


def has(text: str, needle: str) -> bool:
    return needle in text


def analyze_idea_repo(path: Path | None) -> list[Idea]:
    if path is None or not path.is_dir():
        return [Idea("idea_source_available", False, None, "reference repository was not cloned")]

    result: list[Idea] = [Idea("idea_source_available", True, str(path), "reference repository cloned for analysis only")]
    settings = path / "settings.gradle.kts"
    app_build = path / "app/build.gradle.kts"

    settings_text = read(settings) if settings.exists() else ""
    app_text = read(app_build) if app_build.exists() else ""

    result.extend([
        Idea("maven_local_repo", has(settings_text, "mavenLocal()"), rel(settings, path) if settings.exists() else None, "local-only repository idea; not imported into CI by default"),
        Idea("jitpack_repo", has(settings_text, "jitpack.io"), rel(settings, path) if settings.exists() else None, "JitPack repository idea; upstream dev already contains guarded JitPack usage"),
        Idea("morphe_packages", has(settings_text, "MorpheApp"), rel(settings, path) if settings.exists() else None, "Morphe repository idea; upstream dev already has Morphe package repositories"),
        Idea("about_libraries_android_plugin", has(app_text, "about.libraries.android"), rel(app_build, path) if app_build.exists() else None, "license metadata idea; upstream keeps aboutLibraries generation"),
        Idea("ample_runtime", has(app_text, "ample"), rel(app_build, path) if app_build.exists() else None, "Ample integration idea; not force-copied without source contract"),
        Idea("native_cmake", has(app_text, "externalNativeBuild"), rel(app_build, path) if app_build.exists() else None, "native build idea; handled by native/cmake patchers"),
        Idea("packaging_excludes", has(app_text, "packaging"), rel(app_build, path) if app_build.exists() else None, "packaging exclusion idea; upstream already has targeted excludes"),
    ])
    return result


def ensure_import(text: str, import_line: str) -> str:
    if import_line in text:
        return text
    lines = text.splitlines()
    insert_at = 0
    while insert_at < len(lines) and lines[insert_at].startswith("import "):
        insert_at += 1
    lines.insert(insert_at, import_line)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def insert_after_anchor(text: str, anchor: str, block: str) -> str:
    if block.strip() in text:
        return text
    pos = text.find(anchor)
    if pos < 0:
        return text
    end = pos + len(anchor)
    return text[:end] + block + text[end:]


def patch_source_sets(text: str) -> str:
    line = "        getByName(\"main\").assets.srcDir(localHaosOneApkAssetsDir)"
    if line.strip() in text:
        return text
    m = re.search(r"(?m)^\s*sourceSets\s*\{\s*$", text)
    if m:
        insert = "\n" + line
        return text[:m.end()] + insert + text[m.end():]

    android = re.search(r"(?m)^\s*android\s*\{\s*$", text)
    if not android:
        return text
    block = f"\n    sourceSets {{\n{line}\n    }}\n"
    return text[:android.end()] + block + text[android.end():]


def patch_tasks_block(text: str) -> str:
    if "copyLocalHaosOneApkAssets" in text:
        return text
    m = re.search(r"(?m)^\s*tasks\s*\{\s*$", text)
    if not m:
        return text
    block = r'''
    // LOCALHAOS_ONE_APK_BUNDLE
    val writeLocalHaosOneApkManifest by registering {
        val manifestFile = layout.buildDirectory.file("generated/localhaos-one-apk/localhaos-one-apk.json")
        outputs.file(manifestFile)
        doLast {
            val pluginAsset = if (localHaosOneApkPluginProject != null) {
                "localhaos/plugins/revanced-v21-runtime-plugin.apk"
            } else {
                null
            }
            val pluginJson = pluginAsset?.let { "\"$it\"" } ?: "null"
            manifestFile.get().asFile.apply {
                parentFile.mkdirs()
                writeText(
                    """
                    {
                      "version": 1,
                      "source": "localhaos/revanced-manager ideas",
                      "downloadersApi": "localhaos/downloaders/downloaders-api.aar",
                      "runtimePlugin": $pluginJson
                    }
                    """.trimIndent() + "\n"
                )
            }
        }
    }

    val copyLocalHaosOneApkAssets by registering(Sync::class) {
        into(localHaosOneApkAssetsDir)
        dependsOn(writeLocalHaosOneApkManifest)
        dependsOn(":api:assembleRelease")
        from(layout.buildDirectory.file("generated/localhaos-one-apk/localhaos-one-apk.json")) {
            into("localhaos")
            rename { "one-apk.json" }
        }
        from(project(":api").layout.buildDirectory.file("outputs/aar/api-release.aar")) {
            into("localhaos/downloaders")
            rename { "downloaders-api.aar" }
        }
        if (localHaosOneApkPluginProject != null) {
            dependsOn("${localHaosOneApkPluginProject.path}:assembleRelease")
            from(localHaosOneApkPluginProject.layout.buildDirectory.file("outputs/apk/release/${localHaosOneApkPluginProject.name}-release.apk")) {
                into("localhaos/plugins")
                rename { "revanced-v21-runtime-plugin.apk" }
            }
        }
    }

    named("preBuild") {
        dependsOn(copyLocalHaosOneApkAssets)
    }

    matching { it.name.endsWith("Assets") && it.name.startsWith("merge") }.configureEach {
        dependsOn(copyLocalHaosOneApkAssets)
    }
'''
    return text[:m.end()] + block + text[m.end():]


def patch_app_build(repo: Path, changes: list[Change], dry_run: bool) -> None:
    app_build = repo / "app/build.gradle.kts"
    if not app_build.exists():
        return
    before = read(app_build)
    if MARKER in before:
        return

    text = before
    text = ensure_import(text, "import org.gradle.api.tasks.Sync")
    anchor = 'val legalResourcesDir = layout.buildDirectory.dir("generated/legal-res")\n'
    vars_block = '''// LOCALHAOS_ONE_APK_BUNDLE
val localHaosOneApkAssetsDir = layout.buildDirectory.dir("generated/localhaos-one-apk-assets")
val localHaosOneApkPluginProjectPath = ":revanced.v21-runtime-plugin"
val localHaosOneApkPluginProject = rootProject.findProject(localHaosOneApkPluginProjectPath)
'''
    text = insert_after_anchor(text, anchor, vars_block)
    if vars_block.strip() not in text:
        # Conservative fallback: place variables before first android block.
        android_pos = text.find("android {")
        if android_pos >= 0:
            text = text[:android_pos] + vars_block + "\n" + text[android_pos:]
    text = patch_source_sets(text)
    text = patch_tasks_block(text)

    write_if_changed(app_build, before, text, changes, "localhaos-one-apk-bundle", "bundle downloader API and optional runtime plugin as APK assets", repo, dry_run)


def write_report(path: Path | None, changes: list[Change], ideas: list[Idea], applied: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "changed": [asdict(change) for change in changes],
        "ideas": [asdict(idea) for idea in ideas],
        "applied": applied,
        "changed_count": len(changes),
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Apply safe LocalHaos ideas to a dev URV upstream checkout.")
    parser.add_argument("--repo", required=True, type=Path, help="Jman Universal-ReVanced-Manager checkout, expected dev branch")
    parser.add_argument("--idea-repo", default=DEFAULT_IDEA_REPO)
    parser.add_argument("--idea-ref", default=DEFAULT_IDEA_REF)
    parser.add_argument("--scratch", type=Path)
    parser.add_argument("--clone-timeout", type=int, default=60)
    parser.add_argument("--skip-idea-clone", action="store_true")
    parser.add_argument("--disable-one-apk-bundle", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    if not repo.is_dir():
        raise SystemExit(f"repo does not exist: {repo}")

    scratch = args.scratch.resolve() if args.scratch else repo.parent / "localhaos-revanced-manager-ideas"
    idea_path: Path | None = None
    if not args.skip_idea_clone:
        if clone_idea_repo(args.idea_repo, args.idea_ref, scratch, args.clone_timeout):
            idea_path = scratch

    ideas = analyze_idea_repo(idea_path)
    changes: list[Change] = []
    if not args.disable_one_apk_bundle:
        patch_app_build(repo, changes, args.dry_run)

    applied = {
        "idea_repo": args.idea_repo,
        "idea_ref": args.idea_ref,
        "one_apk_bundle": not args.disable_one_apk_bundle,
        "one_apk_assets": [
            "assets/localhaos/one-apk.json",
            "assets/localhaos/downloaders/downloaders-api.aar",
            "assets/localhaos/plugins/revanced-v21-runtime-plugin.apk when module exists",
        ],
    }
    write_report(args.report, changes, ideas, applied)

    for change in changes:
        log(f"{change.rule}: {change.path} :: {change.detail}")
    log(f"ideas analyzed: {len(ideas)}; changes: {len(changes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
