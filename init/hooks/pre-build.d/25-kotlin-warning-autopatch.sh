#!/usr/bin/env bash
set -Eeuo pipefail

python3 "${ROOT_DIR}/init/tools/kotlin_warning_autopatcher.py" \
  --repo "${WORK_DIR}" \
  --report "${OUT_DIR}/warning-autopatch-prebuild.json"
