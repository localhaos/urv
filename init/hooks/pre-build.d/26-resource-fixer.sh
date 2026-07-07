#!/usr/bin/env bash
set -Eeuo pipefail

if [[ -z "${RESOURCE_FIXER+x}" ]]; then
  cfg="${URV_CONFIG:-${ROOT_DIR}/init/config/default.env}"
  if [[ -f "${cfg}" ]]; then
    RESOURCE_FIXER="$(python3 - "${cfg}" <<'PY'
import re
import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding='utf-8')
value = '1'
for line in text.splitlines():
    m = re.match(r'\s*RESOURCE_FIXER\s*=\s*["\']?([^"\']+)["\']?\s*$', line)
    if m:
        value = m.group(1).strip()
print(value)
PY
)"
  fi
fi

[[ "${RESOURCE_FIXER:-1}" == "1" ]] || exit 0

python3 "${ROOT_DIR}/init/tools/patcher_resource_fixer.py" \
  --repo "${WORK_DIR}" \
  --report "${OUT_DIR}/gradle-patcher-resource-prebuild.json"
