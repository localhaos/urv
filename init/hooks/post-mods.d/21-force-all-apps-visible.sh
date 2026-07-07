#!/usr/bin/env bash
set -Eeuo pipefail

python3 - <<'PY'
from pathlib import Path
import os
import sys

repo = Path(os.environ['WORK_DIR'])
paths = list(repo.glob('app/src/main/java/**/util/PM.kt')) + list(repo.glob('app/src/main/kotlin/**/util/PM.kt'))
if not paths:
    print('[URV][all-apps][ERR] PM.kt not found', file=sys.stderr)
    raise SystemExit(2)

pm = paths[0]
text = pm.read_text(encoding='utf-8')
old = '''        val installedApps = scope.async {
            if (!prefs.disableUniversalPatchCheck.get()) emptyList()
            else getInstalledPackages().map { packageInfo ->
                AppInfo(packageInfo.packageName, 0, packageInfo)
            }
        }
'''
new = '''        val installedApps = scope.async {
            getInstalledPackages().map { packageInfo ->
                AppInfo(packageInfo.packageName, 0, packageInfo)
            }
        }
'''
if old in text:
    pm.write_text(text.replace(old, new, 1), encoding='utf-8')
    print(f'[URV][all-apps] forced all installed apps visible: {pm.relative_to(repo)}')
elif 'LOCALHAOS_APP_LIST_FALLBACK' in text and 'getInstalledPackages().map { packageInfo ->' in text:
    print(f'[URV][all-apps] all-apps fallback already present: {pm.relative_to(repo)}')
else:
    print('[URV][all-apps][ERR] expected app-list fallback block not found', file=sys.stderr)
    raise SystemExit(2)
PY
