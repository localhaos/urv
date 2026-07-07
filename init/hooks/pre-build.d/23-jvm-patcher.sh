#!/usr/bin/env bash
set -Eeuo pipefail

if [[ -z "${JVM_PATCHER+x}" ]]; then
  cfg="${URV_CONFIG:-${ROOT_DIR}/init/config/default.env}"
  if [[ -f "${cfg}" ]]; then
    JVM_PATCHER="$(python3 - "${cfg}" <<'PY'
import re
import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding='utf-8')
value = '1'
for line in text.splitlines():
    m = re.match(r'\s*JVM_PATCHER\s*=\s*["\']?([^"\']+)["\']?\s*$', line)
    if m:
        value = m.group(1).strip()
print(value)
PY
)"
  fi
fi

[[ "${JVM_PATCHER:-1}" == "1" ]] || exit 0

python3 "${ROOT_DIR}/init/tools/jvm_patcher.py" \
  --repo "${WORK_DIR}" \
  --report "${OUT_DIR}/gradle-patcher-jvm-prebuild.json"
