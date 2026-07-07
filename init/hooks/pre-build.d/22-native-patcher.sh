#!/usr/bin/env bash
set -Eeuo pipefail

if [[ -z "${NATIVE_PATCHER+x}" ]]; then
  cfg="${URV_CONFIG:-${ROOT_DIR}/init/config/default.env}"
  if [[ -f "${cfg}" ]]; then
    NATIVE_PATCHER="$(python3 - "${cfg}" <<'PY'
import re
import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding='utf-8')
value = '1'
for line in text.splitlines():
    m = re.match(r'\s*NATIVE_PATCHER\s*=\s*["\']?([^"\']+)["\']?\s*$', line)
    if m:
        value = m.group(1).strip()
print(value)
PY
)"
  fi
fi

[[ "${NATIVE_PATCHER:-1}" == "1" ]] || exit 0

python3 "${ROOT_DIR}/init/tools/native_patcher.py" \
  --repo "${WORK_DIR}" \
  --report "${OUT_DIR}/gradle-patcher-native-prebuild.json"
