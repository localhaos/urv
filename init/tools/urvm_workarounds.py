#!/usr/bin/env python3
"""URVM-specific source workarounds applied after generic overlays/patches."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


class WorkaroundError(RuntimeError):
    pass


def log(message: str) -> None:
    print(f"[URV][workaround] {message}", flush=True)


def find_one(repo: Path, patterns: list[str], required: bool = True) -> Path | None:
    for pattern in patterns:
        matches = sorted(repo.glob(pattern))
        if matches:
            return matches[0]
    if required:
        raise WorkaroundError(f"missing file patterns: {', '.join(patterns)}")
    return None


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise WorkaroundError(f"anchor not found for {label}")
    return text.replace(old, new, 1)


def replace_regex(text: str, pattern: str, repl: str, label: str, flags: int = 0) -> str:
    new, count = re.subn(pattern, repl, text, count=1, flags=flags)
    if count != 1:
        raise WorkaroundError(f"regex anchor not found for {label}")
    return new


def patch_pm(repo: Path) -> None:
    pm = find_one(
        repo,
        [
            "app/src/main/java/**/util/PM.kt",
            "app/src/main/kotlin/**/util/PM.kt",
        ],
    )
    assert pm is not None
    text = pm.read_text(encoding="utf-8")

    if "LOCALHAOS_APP_LIST_FALLBACK" in text:
        log("PM.kt already patched")
        return

    if "PreferencesManager" not in text:
        marker = "import app.revanced.manager.domain.repository.PatchBundleRepository\n"
        text = replace_once(
            text,
            marker,
            marker + "import app.revanced.manager.domain.manager.PreferencesManager\n",
            "PM PreferencesManager import",
        )

    if "prefs: PreferencesManager" not in text:
        text = replace_regex(
            text,
            r"(class\s+PM\s*\(\s*private\s+val\s+app:\s+Application,\s*patchBundleRepository:\s+PatchBundleRepository,\s*)(private\s+val\s+uninstaller:\s+PackageUninstaller)",
            r"\1prefs: PreferencesManager,\n    \2",
            "PM constructor prefs injection",
            flags=re.S,
        )

    old_block = '''    val appList = patchBundleRepository.enabledBundlesInfoFlow.map { bundles ->
        val compatibleApps = scope.async {
            val compatiblePackages = bundles
                .flatMap { (_, bundle) -> bundle.patches }
                .flatMap { it.compatiblePackages.orEmpty() }
                .groupingBy { it.packageName }
                .eachCount()

            compatiblePackages.keys.map { pkg ->
                getPackageInfo(pkg)?.let { packageInfo ->
                    AppInfo(
                        pkg,
                        compatiblePackages[pkg],
                        packageInfo
                    )
                } ?: AppInfo(
                    pkg,
                    compatiblePackages[pkg],
                    null
                )
            }
        }

        val installedApps = scope.async {
            getInstalledPackages().map { packageInfo ->
                AppInfo(
                    packageInfo.packageName,
                    0,
                    packageInfo
                )
            }
        }

        if (compatibleApps.await().isNotEmpty()) {
            (compatibleApps.await() + installedApps.await())
                .distinctBy { it.packageName }
                .sortedWith(
                    compareByDescending<AppInfo> {
                        it.packageInfo != null && (it.patches ?: 0) > 0
                    }.thenByDescending {
                        it.patches
                    }.thenBy {
                        it.packageInfo?.label()
                    }.thenBy { it.packageName }
                )
        } else {
            emptyList()
        }
    }.flowOn(Dispatchers.IO)
'''

    new_block = '''    // LOCALHAOS_APP_LIST_FALLBACK
    // Keep the patchable-app selector usable while bundles are updating, disabled,
    // temporarily empty, or blocked by a transient metadata error. Compatible apps
    // are preferred; installed packages are used as a universal fallback when
    // disableUniversalPatchCheck is enabled.
    val appList = patchBundleRepository.bundleInfoFlow.map { bundles ->
        val compatibleApps = scope.async {
            val compatiblePackages = bundles
                .flatMap { (_, bundle) -> bundle.patches }
                .flatMap { it.compatiblePackages.orEmpty() }
                .groupingBy { it.packageName }
                .eachCount()

            compatiblePackages.keys.map { pkg ->
                getPackageInfo(pkg)?.let { packageInfo ->
                    AppInfo(
                        pkg,
                        compatiblePackages[pkg],
                        packageInfo
                    )
                } ?: AppInfo(
                    pkg,
                    compatiblePackages[pkg],
                    null
                )
            }
        }

        val installedApps = scope.async {
            if (!prefs.disableUniversalPatchCheck.get()) {
                emptyList()
            } else {
                getInstalledPackages().map { packageInfo ->
                    AppInfo(
                        packageInfo.packageName,
                        0,
                        packageInfo
                    )
                }
            }
        }

        val compatible = compatibleApps.await()
        val installed = installedApps.await()
        val base = when {
            compatible.isNotEmpty() && installed.isNotEmpty() -> compatible + installed
            compatible.isNotEmpty() -> compatible
            else -> installed
        }

        base
            .distinctBy { it.packageName }
            .sortedWith(
                compareByDescending<AppInfo> {
                    it.packageInfo != null && (it.patches ?: 0) > 0
                }.thenByDescending {
                    it.patches
                }.thenBy {
                    it.packageInfo?.label()
                }.thenBy { it.packageName }
            )
    }.flowOn(Dispatchers.IO)
'''

    if old_block in text:
        text = text.replace(old_block, new_block, 1)
    else:
        start = text.find("    val appList = ")
        if start < 0:
            raise WorkaroundError("PM.appList declaration not found")
        end = text.find("    private fun getInstalledPackages", start)
        if end < 0:
            raise WorkaroundError("PM.getInstalledPackages anchor not found")
        text = text[:start] + new_block + text[end:]

    pm.write_text(text, encoding="utf-8")
    log(f"patched app list fallback: {pm.relative_to(repo)}")


def patch_bundle_repository(repo: Path) -> None:
    source = find_one(
        repo,
        [
            "app/src/main/java/**/domain/repository/PatchBundleRepository.kt",
            "app/src/main/kotlin/**/domain/repository/PatchBundleRepository.kt",
        ],
    )
    assert source is not None
    text = source.read_text(encoding="utf-8")

    if "LOCALHAOS_ALL_BUNDLE_INFO_FLOW" in text:
        log("PatchBundleRepository.kt already patched")
        return

    old = "    val bundleInfoFlow = enabledBundlesInfoFlow\n"
    new = "    // LOCALHAOS_ALL_BUNDLE_INFO_FLOW\n    val bundleInfoFlow = allBundlesInfoFlow\n"
    if old in text:
        source.write_text(text.replace(old, new, 1), encoding="utf-8")
        log(f"patched all-bundle UI flow: {source.relative_to(repo)}")
    else:
        log("bundleInfoFlow alias not present; skipping repository flow patch")


def patch_settings(repo: Path) -> None:
    settings = repo / "settings.gradle.kts"
    if not settings.exists():
        log("settings.gradle.kts missing; skipping optional module workaround")
        return

    text = settings.read_text(encoding="utf-8")
    if "LOCALHAOS_OPTIONAL_MODULES" in text:
        log("settings.gradle.kts already patched")
        return
    if "fun includeIfAvailable(path: String)" in text:
        log("optional module include helper already exists")
        return

    old = 'rootProject.name = "universal-revanced-manager"\ninclude(":app", ":api", ":morphe-runtime", ":ample-runtime")\n'
    new = '''rootProject.name = "universal-revanced-manager"

// LOCALHAOS_OPTIONAL_MODULES
// Dev/main variants do not always ship the same runtime modules. Keep bootstrap
// builds alive by including optional modules only when their Gradle descriptor exists.
fun moduleExists(path: String): Boolean {
    val relativePath = path.removePrefix(":").replace(':', '/')
    val projectDir = rootDir.resolve(relativePath)
    return projectDir.isDirectory && (
        projectDir.resolve("build.gradle.kts").exists() ||
            projectDir.resolve("build.gradle").exists()
        )
}

fun includeIfAvailable(path: String) {
    if (moduleExists(path)) include(path)
}

include(":app", ":api")
includeIfAvailable(":morphe-runtime")
includeIfAvailable(":ample-runtime")
includeIfAvailable(":revanced.v21-runtime-plugin")
'''
    if old in text:
        settings.write_text(text.replace(old, new, 1), encoding="utf-8")
        log("patched optional Gradle modules")
    else:
        log("settings include layout not recognized; skipping optional module workaround")


def run(repo: Path) -> None:
    patch_pm(repo)
    patch_bundle_repository(repo)
    patch_settings(repo)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    if not repo.is_dir():
        raise WorkaroundError(f"repo path does not exist: {repo}")
    run(repo)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except WorkaroundError as exc:
        print(f"[URV][workaround][ERR] {exc}", file=sys.stderr, flush=True)
        raise SystemExit(2)
