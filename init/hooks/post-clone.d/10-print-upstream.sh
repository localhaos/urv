#!/usr/bin/env bash
set -Eeuo pipefail

echo "[URV][post-clone] repo=${UPSTREAM_REPO}"
echo "[URV][post-clone] ref=${UPSTREAM_REF}"
git -C "${WORK_DIR}" rev-parse --short HEAD || true
