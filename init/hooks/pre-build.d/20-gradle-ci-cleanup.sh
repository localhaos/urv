#!/usr/bin/env bash
set -Eeuo pipefail

python3 - <<'PY'
from pathlib import Path
import os
import re
import sys

repo = Path(os.environ['WORK_DIR']).resolve()

def log(msg: str) -> None:
    print(f"[URV][gradle-cleanup] {msg}", flush=True)

def fail(msg: str) -> None:
    print(f"[URV][gradle-cleanup][ERR] {msg}", file=sys.stderr, flush=True)
    raise SystemExit(2)

def append_gradle_property(path: Path, key: str, value: str) -> None:
    existing = path.read_text(encoding='utf-8') if path.exists() else ''
    pattern = re.compile(rf'^\s*{re.escape(key)}\s*=', re.M)
    if pattern.search(existing):
        updated = pattern.sub(f'{key}={value}', existing, count=1)
    else:
        sep = '' if not existing or existing.endswith('\n') else '\n'
        updated = existing + sep + f'{key}={value}\n'
    if updated != existing:
        path.write_text(updated, encoding='utf-8')
        log(f'set {key} in {path.relative_to(repo)}')

# Fix hard CI failure: upstream checks project.hasProperty("signAsDebug").
append_gradle_property(repo / 'gradle.properties', 'signAsDebug', 'true')

# Fix Kotlin/AGP publication warning for :api release component.
api = repo / 'api' / 'build.gradle.kts'
if api.exists():
    text = api.read_text(encoding='utf-8')
    original = text
    if 'singleVariant("release")' not in text:
        marker = '    buildTypes {\n'
        block = '''    publishing {
        singleVariant("release") {}
    }

'''
        if marker in text:
            text = text.replace(marker, block + marker, 1)
        else:
            marker = 'android {\n'
            if marker in text:
                text = text.replace(marker, marker + block, 1)
            else:
                fail('api android block not found; cannot patch release publication warning')
    if text != original:
        api.write_text(text, encoding='utf-8')
        log('patched api publication singleVariant("release")')
else:
    fail('api/build.gradle.kts missing; cannot patch api publication warning')

# Replace source-level Kotlin deprecated Android API usage.
webview_files = sorted(repo.glob('api/src/main/kotlin/**/WebViewActivity.kt'))
for source in webview_files:
    text = source.read_text(encoding='utf-8')
    original = text
    if 'getParcelableExtra(KEY, Parameters::class.java)' not in text:
        if 'import android.os.Build\n' not in text:
            text = text.replace('import android.os.Bundle\n', 'import android.os.Build\nimport android.os.Bundle\n', 1)
        text = text.replace(
            '        val params = intent.getParcelableExtra<Parameters>(KEY)!!\n',
            '''        val params = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            intent.getParcelableExtra(KEY, Parameters::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra(KEY) as? Parameters
        }!!
''',
            1,
        )
    if text != original:
        source.write_text(text, encoding='utf-8')
        log(f'patched typed Parcelable extra API: {source.relative_to(repo)}')
    if 'getParcelableExtra<Parameters>(KEY)' in text:
        fail(f'deprecated Parcelable extra call still present: {source.relative_to(repo)}')

# Replace source-level Morphe/ReVanced deprecated API usage.
entry = repo / 'morphe-runtime/src/main/java/app/urv/manager/morphe/runtime/MorpheRuntimeEntry.kt'
if entry.exists():
    text = entry.read_text(encoding='utf-8')
    original = text
    text = text.replace('result["use"] = patch.use', 'result["use"] = patch.default')
    text = text.replace('result["key"] = option.key', 'result["key"] = option.name')
    text = text.replace('result["title"] = option.title ?: option.key', 'result["title"] = option.name')
    old = '''        } ?: patch.compatiblePackages?.map { (pkg, versions) ->
            linkedMapOf(
                "packageName" to pkg,
                "versions" to versions?.toList()
            )
        }
'''
    text = text.replace(old, '        }\n', 1)
    if text != original:
        entry.write_text(text, encoding='utf-8')
        log(f'patched deprecated Morphe runtime API: {entry.relative_to(repo)}')
    for needle in ('patch.use', 'patch.compatiblePackages', 'option.key', 'option.title'):
        if needle in text:
            fail(f'deprecated Morphe runtime API still present: {needle} in {entry.relative_to(repo)}')
else:
    log('MorpheRuntimeEntry.kt missing; skipping Morphe runtime deprecation patch')

loader = repo / 'morphe-runtime/src/main/java/app/urv/manager/patcher/morphe/MorphePatchBundleLoader.kt'
if loader.exists():
    text = loader.read_text(encoding='utf-8')
    original = text
    old = '''                val compatiblePackages = patch.compatiblePackages
                    ?: return@filter true

                compatiblePackages.any { (name, _) -> name == packageName }
'''
    new = '''                val compatibility = patch.compatibility
                    ?: return@filter true

                compatibility.any { it.packageName == packageName }
'''
    text = text.replace(old, new, 1)
    if text != original:
        loader.write_text(text, encoding='utf-8')
        log(f'patched deprecated Morphe loader API: {loader.relative_to(repo)}')
    if 'patch.compatiblePackages' in text:
        fail(f'deprecated Morphe loader API still present: {loader.relative_to(repo)}')
else:
    log('MorphePatchBundleLoader.kt missing; skipping Morphe loader deprecation patch')

process = repo / 'morphe-runtime/src/main/java/app/urv/manager/patcher/runtime/process/MorphePatcherProcess.kt'
if process.exists():
    text = process.read_text(encoding='utf-8')
    original = text
    old = '            Looper.prepareMainLooper()\n'
    new = '''            if (Looper.myLooper() == null) {
                Looper::class.java.getDeclaredMethod("prepareMainLooper").invoke(null)
            }
'''
    text = text.replace(old, new, 1)
    if text != original:
        process.write_text(text, encoding='utf-8')
        log(f'patched deprecated Looper bootstrap API: {process.relative_to(repo)}')
    if 'Looper.prepareMainLooper()' in text:
        fail(f'deprecated Looper API still present: {process.relative_to(repo)}')
else:
    log('MorphePatcherProcess.kt missing; skipping Looper deprecation patch')

merger = repo / 'morphe-runtime/src/main/java/app/urv/manager/patcher/split/Merger.kt'
if merger.exists():
    text = merger.read_text(encoding='utf-8')
    original = text
    text = text.replace('import com.reandroid.arsc.header.TableHeader\n', '')
    text = text.replace('            val header = module.tableBlock.headerBlock as? TableHeader ?: return@forEach\n', '            val header = module.tableBlock.headerBlock\n')
    if text != original:
        merger.write_text(text, encoding='utf-8')
        log(f'patched unnecessary TableHeader cast: {merger.relative_to(repo)}')
    if 'as? TableHeader' in text:
        fail(f'unnecessary TableHeader cast still present: {merger.relative_to(repo)}')
else:
    log('Merger.kt missing; skipping unnecessary cast patch')

# Reduce known Gradle/AGP deprecation warnings in app build script.
app = repo / 'app' / 'build.gradle.kts'
if app.exists():
    text = app.read_text(encoding='utf-8')
    original = text
    text = text.replace('getFilter(com.android.build.OutputFile.ABI)', 'getFilter("ABI")')
    text = text.replace(
        'from("$buildDir/intermediates/javac/release/classes") {',
        'from(layout.buildDirectory.dir("intermediates/javac/release/classes")) {'
    )
    text = text.replace(
        'from("${buildDir}/intermediates/javac/release/classes") {',
        'from(layout.buildDirectory.dir("intermediates/javac/release/classes")) {'
    )
    text = re.sub(r'from\("\$buildDir/([^"]+)"\)', lambda m: f'from(layout.buildDirectory.dir("{m.group(1)}"))', text)
    text = re.sub(r'from\("\$\{buildDir\}/([^"]+)"\)', lambda m: f'from(layout.buildDirectory.dir("{m.group(1)}"))', text)
    text = re.sub(r'\bbuildDir\.resolve\("([^"]+)"\)', lambda m: f'layout.buildDirectory.dir("{m.group(1)}").get().asFile', text)
    text = re.sub(r'File\(buildDir,\s*"([^"]+)"\)', lambda m: f'layout.buildDirectory.file("{m.group(1)}").get().asFile', text)
    text = text.replace('$buildDir/', '${layout.buildDirectory.get().asFile}/')
    text = text.replace('${buildDir}/', '${layout.buildDirectory.get().asFile}/')
    if text != original:
        app.write_text(text, encoding='utf-8')
        log('patched app Gradle deprecated Java API anchors')
    leftovers = []
    if 'com.android.build.OutputFile' in text:
        leftovers.append('com.android.build.OutputFile')
    if re.search(r'(?<!layout\.)\bbuildDir\b|\$\{?buildDir\}?', text):
        leftovers.append('buildDir')
    if leftovers:
        fail('deprecated Gradle anchors still present in app/build.gradle.kts: ' + ', '.join(leftovers))
else:
    fail('app/build.gradle.kts missing; cannot patch Gradle warning anchors')
PY
