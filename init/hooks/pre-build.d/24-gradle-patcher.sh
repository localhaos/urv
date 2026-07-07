#!/usr/bin/env bash
set -Eeuo pipefail

[[ "${GRADLE_PATCHER:-${GRADLE_AUTOFIX:-1}}" == "1" ]] || exit 0

python3 "${ROOT_DIR}/init/tools/gradle_patcher.py" \
  --repo "${WORK_DIR}" \
  --report "${OUT_DIR}/gradle-patcher-prebuild.json"
