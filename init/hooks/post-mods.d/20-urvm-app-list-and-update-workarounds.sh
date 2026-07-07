#!/usr/bin/env bash
set -Eeuo pipefail

python3 - <<'PY'
from __future__ import annotations

from pathlib import Path
import re
import sys

work = Path(__import__('os').environ['WORK_DIR'])


def log(msg: str) -> None:
    print(f"[URV][workaround] {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"[URV][workaround][ERR] {msg}", file=sys.stderr, flush=True)
    raise SystemExit(2)


def find_one(pattern: str, required: bool = True) -> Path | None:
    matches = sorted(work.glob(pattern))
    if matches:
        return matches[0]
    if required:
        fail(f"missing file pattern: {pattern}")
    return None


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        fail(f"anchor not found for {label}")
    return text.replace(old, new, 1)


def replace_regex(text: str, pattern: str, repl: str, label: str, flags: int = 0) -> str:
    new, count = re.subn(pattern, repl, text, count=1, flags=flags)
    if count != 1:
        fail(f"regex anchor not found for {label}")
    return new


def patch_pm() -> None:
    pm = find_one('app/src/main/java/**/util/PM.kt') or find_one('app/src/main/kotlin/**/util/PM.kt')
    text = pm.read_text(encoding='utf-8')

    if 'LOCALHAOS_APP_LIST_FALLBACK' in text:
        log('PM.kt already patched')
        return

    if 'PreferencesManager' not in text:
        marker = 'import app.revanced.manager.domain.repository.PatchBundleRepository\n'
        text = replace_once(
            text,
            marker,
            marker + 'import app.revanced.manager.domain.manager.PreferencesManager\n',
            'PM PreferencesManager import',
        )

    # Constructor variant used by URVM main/dev: app, patchBundleRepository, uninstaller.
    # Koin singleOf(::PM) can resolve the additional PreferencesManager dependency.
    text = replace_regex(
        text,
        r'(class\s+PM\s*\(\s*private\s+val\s+app:\s+Application,\s*patchBundleRepository:\s+PatchBundleRepository,\s*)(private\s+val\s+uninstaller:\s+PackageUninstaller)',
        r'\1prefs: PreferencesManager,\n    \2',
        'PM constructor prefs injection',
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
    // temporarily empty, or blocked by a transient metadata error. This mirrors the
    // older ReVanced Manager workaround: compatible apps are preferred, installed
    // packages are used as a universal fallback when disableUniversalPatchCheck is enabled.
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

    if old_block not in text:
        # Fallback for already partially changed upstream: replace the whole val appList block
        # by brace-balanced scan.
        start = text.find('    val appList = ')
        if start < 0:
            fail('PM.appList declaration not found')
        flow = text.find('    private fun getInstalledPackages', start)
        if flow < 0:
            fail('PM.getInstalledPackages anchor not found')
        text = text[:start] + new_block + text[flow:]
    else:
        text = text.replace(old_block, new_block, 1)

    pm.write_text(text, encoding='utf-8')
    log(f'patched app list fallback: {pm.relative_to(work)}')


def patch_bundle_repository() -> None:
    repo = find_one('app/src/main/java/**/domain/repository/PatchBundleRepository.kt') or find_one('app/src/main/kotlin/**/domain/repository/PatchBundleRepository.kt')
    text = repo.read_text(encoding='utf-8')

    if 'LOCALHAOS_ALL_BUNDLE_INFO_FLOW' in text:
        log('PatchBundleRepository.kt already patched')
        return

    # Keep UI reads resilient during updates: bundleInfoFlow should expose all loaded metadata,
    # while enabledBundlesInfoFlow remains available for strict patching/version logic.
    old = '    val bundleInfoFlow = enabledBundlesInfoFlow\n'
    new = '    // LOCALHAOS_ALL_BUNDLE_INFO_FLOW\n    val bundleInfoFlow = allBundlesInfoFlow\n'
    if old in text:
        text = text.replace(old, new, 1)
        repo.write_text(text, encoding='utf-8')
        log(f'patched all-bundle UI flow: {repo.relative_to(work)}')
    else:
        log('bundleInfoFlow alias not present; skipping repository flow patch')


def patch_settings() -> None:
    settings = work / 'settings.gradle.kts'
    if not settings.exists():
        log('settings.gradle.kts missing; skipping optional module workaround')
        return

    text = settings.read_text(encoding='utf-8')
    if 'LOCALHAOS_OPTIONAL_MODULES' in text:
        log('settings.gradle.kts already patched')
        return

    if 'fun includeIfAvailable(path: String)' in text:
        log('optional module include helper already exists')
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
        settings.write_text(text.replace(old, new, 1), encoding='utf-8')
        log('patched optional Gradle modules')
    else:
        log('settings include layout not recognized; skipping optional module workaround')


patch_pm()
patch_bundle_repository()
patch_settings()
PY
