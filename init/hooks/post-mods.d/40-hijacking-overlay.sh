#!/usr/bin/env bash
set -Eeuo pipefail

[[ "${HIJACKING_OVERLAY:-1}" == "1" ]] || exit 0

python3 "${ROOT_DIR}/init/tools/hijacking_overlay.py" \
  --repo-root "${ROOT_DIR}" \
  --work-dir "${WORK_DIR}" \
  --report "${OUT_DIR}/hijacking-overlay.json"
