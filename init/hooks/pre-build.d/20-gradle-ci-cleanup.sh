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
            text = text.replace(marker, marker + block, 1)
    if text != original:
        api.write_text(text, encoding='utf-8')
        log('patched api publication singleVariant("release")')
else:
    log('api/build.gradle.kts missing; skipping api publication patch')

# Reduce known Gradle/AGP deprecation warnings in app build script.
app = repo / 'app' / 'build.gradle.kts'
if app.exists():
    text = app.read_text(encoding='utf-8')
    original = text
    text = text.replace('getFilter(com.android.build.OutputFile.ABI)', 'getFilter("ABI")')
    text = re.sub(r'\bbuildDir\.resolve\("([^"]+)"\)', r'layout.buildDirectory.dir("\1").get().asFile', text)
    text = re.sub(r'File\(buildDir,\s*"([^"]+)"\)', r'layout.buildDirectory.file("\1").get().asFile', text)
    text = text.replace('$buildDir/', '${layout.buildDirectory.get().asFile}/')
    if text != original:
        app.write_text(text, encoding='utf-8')
        log('patched app Gradle deprecation anchors')
else:
    log('app/build.gradle.kts missing; skipping app Gradle warning patch')
PY
