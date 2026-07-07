#!/usr/bin/env bash
set -Eeuo pipefail

python3 "${ROOT_DIR}/init/tools/gradle_build_autofixer.py" \
  --repo "${WORK_DIR}" \
  --report "${OUT_DIR}/gradle-autofix-prebuild.json"
