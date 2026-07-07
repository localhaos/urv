#!/usr/bin/env bash
set -Eeuo pipefail

cfg="${URV_CONFIG:-${ROOT_DIR}/init/config/default.env}"
read_cfg() {
  local key="$1"
  local fallback="$2"
  if [[ ! -f "${cfg}" ]]; then
    printf '%s\n' "${fallback}"
    return 0
  fi
  python3 - "${cfg}" "${key}" "${fallback}" <<'PY'
import re
import sys
from pathlib import Path
cfg, key, fallback = sys.argv[1:4]
text = Path(cfg).read_text(encoding='utf-8')
value = fallback
for line in text.splitlines():
    m = re.match(rf'\s*{re.escape(key)}\s*=\s*["\']?([^"\']+)["\']?\s*$', line)
    if m:
        value = m.group(1).strip()
print(value)
PY
}

LOCALHAOS_IDEAS="${LOCALHAOS_IDEAS:-$(read_cfg LOCALHAOS_IDEAS 1)}"
ONE_APK_BUNDLE="${ONE_APK_BUNDLE:-$(read_cfg ONE_APK_BUNDLE 1)}"
LOCALHAOS_IDEAS_CLONE="${LOCALHAOS_IDEAS_CLONE:-$(read_cfg LOCALHAOS_IDEAS_CLONE 1)}"
LOCALHAOS_IDEA_REPO="${LOCALHAOS_IDEA_REPO:-$(read_cfg LOCALHAOS_IDEA_REPO https://github.com/localhaos/revanced-manager.git)}"
LOCALHAOS_IDEA_REF="${LOCALHAOS_IDEA_REF:-$(read_cfg LOCALHAOS_IDEA_REF main)}"

[[ "${LOCALHAOS_IDEAS}" == "1" ]] || exit 0

args=(
  --repo "${WORK_DIR}"
  --idea-repo "${LOCALHAOS_IDEA_REPO}"
  --idea-ref "${LOCALHAOS_IDEA_REF}"
  --scratch "${OUT_DIR}/localhaos-revanced-manager-ideas"
  --report "${OUT_DIR}/gradle-patcher-localhaos-ideas.json"
)

[[ "${ONE_APK_BUNDLE}" == "1" ]] || args+=(--disable-one-apk-bundle)
[[ "${LOCALHAOS_IDEAS_CLONE}" == "1" ]] || args+=(--skip-idea-clone)

python3 "${ROOT_DIR}/init/tools/localhaos_ideas_importer.py" "${args[@]}"
