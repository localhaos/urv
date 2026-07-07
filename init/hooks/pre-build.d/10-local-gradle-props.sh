#!/usr/bin/env bash
set -Eeuo pipefail

if [[ -d "${WORK_DIR}" && -n "${ANDROID_HOME:-}" ]]; then
  printf 'sdk.dir=%s\n' "${ANDROID_HOME}" > "${WORK_DIR}/local.properties"
fi

# Upstream settings.gradle.kts can read GitHub Packages credentials from env:
# GITHUB_ACTOR and GITHUB_TOKEN. GitHub Actions already exports them.
