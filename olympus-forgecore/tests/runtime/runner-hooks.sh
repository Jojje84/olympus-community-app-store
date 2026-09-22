#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -d "${ROOT}/umbrel" ]]; then
  PACKAGE_ROOT="${ROOT}/umbrel"
else
  PACKAGE_ROOT="${ROOT}"
fi

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT
export FORGECORE_APP_ROOT="${tmp}/app"
export FORGECORE_STORAGE_ROOT="${tmp}/storage"
export FORGECORE_RUNTIME_VERSION="0.1.0-beta.32"
mkdir -p "${FORGECORE_APP_ROOT}/state" "${FORGECORE_STORAGE_ROOT}/logs"

source "${PACKAGE_ROOT}/data/bin/runner-manager.sh"
prepare_runner_hooks "jojje84-forgecore"
hook="${FORGECORE_APP_ROOT}/hooks/job-started-jojje84-forgecore.sh"

if GITHUB_WORKFLOW="Release" GITHUB_EVENT_NAME="workflow_dispatch" GITHUB_REF_NAME="v0.1.0-beta.23" "${hook}"; then
  echo "stale release was not rejected" >&2
  exit 1
fi

if GITHUB_WORKFLOW="Release channel preflight" GITHUB_EVENT_NAME="push" GITHUB_REF_NAME="feat/forgecore-v1-runtime" "${hook}"; then
  echo "stale preflight push was not rejected" >&2
  exit 1
fi

GITHUB_WORKFLOW="Release" GITHUB_EVENT_NAME="workflow_dispatch" GITHUB_REF_NAME="v0.1.0-beta.33" "${hook}"
GITHUB_WORKFLOW="ForgeCore CI" GITHUB_EVENT_NAME="workflow_dispatch" GITHUB_REF_NAME="feat/forgecore-v1-runtime" "${hook}"
test -s "${FORGECORE_APP_ROOT}/state/runner-jojje84-forgecore.job-started-epoch"

echo "ForgeCore runner hook safety tests: OK"
