#!/usr/bin/env bash
set -Eeuo pipefail

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
  --cache "${OUT_DIR}/template-overlay.cache.json" \
  --report "${OUT_DIR}/template-overlay.json"
