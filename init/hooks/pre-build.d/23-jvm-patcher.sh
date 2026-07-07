#!/usr/bin/env bash
set -Eeuo pipefail

[[ "${JVM_PATCHER:-1}" == "1" ]] || exit 0

python3 "${ROOT_DIR}/init/tools/jvm_patcher.py" \
  --repo "${WORK_DIR}" \
  --report "${OUT_DIR}/gradle-patcher-jvm-prebuild.json"
