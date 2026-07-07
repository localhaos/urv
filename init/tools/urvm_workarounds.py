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


def patch_pm(repo: Path) -> None:
    pm = find_one(repo, ["app/src/main/java/**/util/PM.kt", "app/src/main/kotlin/**/util/PM.kt"])
    assert pm is not None
    text = pm.read_text(encoding="utf-8")
    original = text

    if "LOCALHAOS_APP_LIST_FALLBACK" not in text:
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
    // Always keep installed apps visible in the patch selector. Compatible apps
    // remain sorted first, but an empty or broken bundle metadata state no longer
    // collapses the selector to an empty list.
    val appList = patchBundleRepository.bundleInfoFlow.map { bundles ->
        val compatibleApps = scope.async {
            val compatiblePackages = bundles
                .flatMap { (_, bundle) -> bundle.patches }
                .flatMap { it.compatiblePackages.orEmpty() }
                .groupingBy { it.packageName }
                .eachCount()

            compatiblePackages.keys.map { pkg ->
                getPackageInfo(pkg)?.let { packageInfo ->
                    AppInfo(pkg, compatiblePackages[pkg], packageInfo)
                } ?: AppInfo(pkg, compatiblePackages[pkg], null)
            }
        }

        val installedApps = scope.async {
            getInstalledPackages().map { packageInfo ->
                AppInfo(packageInfo.packageName, 0, packageInfo)
            }
        }

        val compatible = compatibleApps.await()
        val installed = installedApps.await()
        val base = when {
            compatible.isNotEmpty() && installed.isNotEmpty() -> compatible + installed
            compatible.isNotEmpty() -> compatible
            else -> installed
        }

        base.distinctBy { it.packageName }.sortedWith(
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

    if "MATCH_DISABLED_COMPONENTS" not in text:
        old_get_installed = '''    private fun getInstalledPackages(flags: Int = 0): List<PackageInfo> =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU)
            app.packageManager.getInstalledPackages(PackageInfoFlags.of(flags.toLong()))
        else
            app.packageManager.getInstalledPackages(flags)
'''
        new_get_installed = '''    private fun getInstalledPackages(flags: Int = 0): List<PackageInfo> {
        val effectiveFlags = flags or PackageManager.MATCH_DISABLED_COMPONENTS
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU)
            app.packageManager.getInstalledPackages(PackageInfoFlags.of(effectiveFlags.toLong()))
        else
            app.packageManager.getInstalledPackages(effectiveFlags)
    }
'''
        if old_get_installed in text:
            text = text.replace(old_get_installed, new_get_installed, 1)
        else:
            log("PM getInstalledPackages layout not recognized; app-list fallback remains active")

    if text != original:
        pm.write_text(text, encoding="utf-8")
        log(f"patched PM app-list fallback/query flags: {pm.relative_to(repo)}")
    else:
        log("PM.kt already patched")


def patch_bundle_repository(repo: Path) -> None:
    source = find_one(repo, [
        "app/src/main/java/**/domain/repository/PatchBundleRepository.kt",
        "app/src/main/kotlin/**/domain/repository/PatchBundleRepository.kt",
    ])
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


def patch_http_module(repo: Path) -> None:
    source = find_one(repo, ["app/src/main/java/**/di/HttpModule.kt", "app/src/main/kotlin/**/di/HttpModule.kt"], required=False)
    if source is None:
        log("HttpModule.kt missing; skipping network patch")
        return
    text = source.read_text(encoding="utf-8")
    original = text
    if "HttpRequestRetry" not in text:
        text = replace_once(
            text,
            "import io.ktor.client.plugins.HttpTimeout\n",
            "import io.ktor.client.plugins.HttpTimeout\nimport io.ktor.client.plugins.HttpRequestRetry\n",
            "HttpRequestRetry import",
        )
    old_dns = '''                dns(object : Dns {
                    override fun lookup(hostname: String): List<InetAddress> {
                        val addresses = Dns.SYSTEM.lookup(hostname)
                        return if (hostname == "raw.githubusercontent.com") {
                            addresses.filterIsInstance<Inet4Address>()
                        } else {
                            addresses
                        }
                    }
                })
'''
    new_dns = '''                dns(object : Dns {
                    override fun lookup(hostname: String): List<InetAddress> {
                        val addresses = Dns.SYSTEM.lookup(hostname)
                        val ipv4PreferredHosts = setOf(
                            "raw.githubusercontent.com",
                            "github.com",
                            "api.github.com",
                            "objects.githubusercontent.com",
                            "codeload.github.com"
                        )
                        return if (hostname.lowercase() in ipv4PreferredHosts) {
                            addresses.filterIsInstance<Inet4Address>().ifEmpty { addresses }
                        } else {
                            addresses
                        }
                    }
                })
'''
    if old_dns in text:
        text = text.replace(old_dns, new_dns, 1)
    text = text.replace("connectTimeoutMillis = 10_000", "connectTimeoutMillis = 20_000")
    text = text.replace("socketTimeoutMillis = 60_000", "socketTimeoutMillis = 120_000")
    text = text.replace("requestTimeoutMillis = 5 * 60_000", "requestTimeoutMillis = 10 * 60_000")
    if "install(HttpRequestRetry)" not in text:
        marker = '''        install(UserAgent) {
            agent = fallbackUserAgent
        }
'''
        retry = '''        install(HttpRequestRetry) {
            retryOnServerErrors(maxRetries = 3)
            retryOnException(maxRetries = 3, retryOnTimeout = true)
            exponentialDelay()
        }
'''
        text = replace_once(text, marker, retry + marker, "HttpRequestRetry block")
    if text != original:
        source.write_text(text, encoding="utf-8")
        log(f"patched network client: {source.relative_to(repo)}")
    else:
        log("HttpModule.kt already patched")


def patch_parcelable_url(repo: Path) -> None:
    source = find_one(repo, [
        "api/src/main/kotlin/**/plugin/downloader/Parcelables.kt",
        "api/src/main/java/**/plugin/downloader/Parcelables.kt",
    ], required=False)
    if source is None:
        return
    text = source.read_text(encoding="utf-8")
    old = "        connectTimeout = 10_000\n        connect()\n"
    new = "        connectTimeout = 20_000\n        readTimeout = 120_000\n        instanceFollowRedirects = true\n        connect()\n"
    if old in text and "readTimeout = 120_000" not in text:
        source.write_text(text.replace(old, new, 1), encoding="utf-8")
        log(f"patched URL fetch timeout: {source.relative_to(repo)}")


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
    patch_http_module(repo)
    patch_parcelable_url(repo)
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
