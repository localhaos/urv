#!/usr/bin/env bash
set -Eeuo pipefail

if [[ -z "${TEMPLATE_OVERLAY+x}" ]]; then
  cfg="${URV_CONFIG:-${ROOT_DIR}/init/config/default.env}"
  if [[ -f "${cfg}" ]]; then
    TEMPLATE_OVERLAY="$(python3 - "${cfg}" <<'PY'
import re
import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding='utf-8')
value = '1'
for line in text.splitlines():
    m = re.match(r'\s*TEMPLATE_OVERLAY\s*=\s*["\']?([^"\']+)["\']?\s*$', line)
    if m:
        value = m.group(1).strip()
print(value)
PY
)"
  fi
fi

[[ "${TEMPLATE_OVERLAY:-1}" == "1" ]] || exit 0

overlay="${ROOT_DIR}/init/templates/overlay"
if ! find "${overlay}" -type f ! -name '.gitkeep' -print -quit | grep -q .; then
  echo '[URV][templates] overlay empty; skipping'
  exit 0
fi

python3 "${ROOT_DIR}/init/tools/hijacking_overlay.py" \
  --repo-root "${ROOT_DIR}" \
  --work-dir "${WORK_DIR}" \
  --overlay "${overlay}" \
  --cache "${OUT_DIR}/gradle-patcher-template-overlay.cache.json" \
  --report "${OUT_DIR}/gradle-patcher-template-overlay.json"
