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
export FORGECORE_RUNTIME_VERSION="0.1.0-beta.34"
mkdir -p "${FORGECORE_APP_ROOT}/state" "${FORGECORE_STORAGE_ROOT}/logs"
touch "${FORGECORE_APP_ROOT}/state/dependencies.ready"

source "${PACKAGE_ROOT}/data/bin/runner-manager.sh"
prepare_runner_hooks "jojje84-forgecore"
hook="${FORGECORE_APP_ROOT}/hooks/job-started-jojje84-forgecore.sh"
export FORGECORE_HOOK_STATE_DIR="${FORGECORE_APP_ROOT}/state"
export FORGECORE_HOOK_SLUG="jojje84-forgecore"
export FORGECORE_HOOK_DEPENDENCY_READY_FILE="${FORGECORE_APP_ROOT}/state/dependencies.ready"
export FORGECORE_HOOK_DEPENDENCY_ERROR_FILE="${FORGECORE_APP_ROOT}/state/dependencies.error"

if GITHUB_WORKFLOW="Release" GITHUB_EVENT_NAME="workflow_dispatch" GITHUB_REF_NAME="v0.1.0-beta.23" "${hook}"; then
  echo "stale release was not rejected" >&2
  exit 1
fi

if GITHUB_WORKFLOW="Release channel preflight" GITHUB_EVENT_NAME="push" GITHUB_REF_NAME="feat/forgecore-v1-runtime" "${hook}"; then
  echo "stale preflight push was not rejected" >&2
  exit 1
fi

GITHUB_WORKFLOW="Release" GITHUB_EVENT_NAME="workflow_dispatch" GITHUB_REF_NAME="v0.1.0-beta.35" "${hook}"
GITHUB_WORKFLOW="ForgeCore CI" GITHUB_EVENT_NAME="workflow_dispatch" GITHUB_REF_NAME="feat/forgecore-v1-runtime" "${hook}"
test -s "${FORGECORE_APP_ROOT}/state/runner-jojje84-forgecore.job-started-epoch"

echo "ForgeCore runner hook safety tests: OK"
