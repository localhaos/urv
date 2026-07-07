#!/usr/bin/env bash
set -Eeuo pipefail

python3 "${ROOT_DIR}/init/tools/urvm_workarounds.py" --repo "${WORK_DIR}"
python3 "${ROOT_DIR}/init/tools/urv_integrations.py" --repo "${WORK_DIR}"
