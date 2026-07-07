#!/usr/bin/env bash
set -Eeuo pipefail

python3 "${ROOT_DIR}/init/tools/add_vineflower_gradle.py" \
  --repo "${WORK_DIR}" \
  --version "${VINEFLOWER_VERSION:-1.12.0}"
