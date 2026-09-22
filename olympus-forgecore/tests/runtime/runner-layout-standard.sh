#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -d "${ROOT}/umbrel" ]]; then
  PACKAGE_ROOT="${ROOT}/umbrel"
else
  PACKAGE_ROOT="${ROOT}"
fi
MANAGER="${PACKAGE_ROOT}/data/bin/runner-manager.sh"

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

export FORGECORE_APP_ROOT="${tmp}/app"
export FORGECORE_STORAGE_ROOT="${tmp}/storage"
export FORGECORE_RUNNER_DIST_ROOT="${tmp}/dist"

mkdir -p \
  "${FORGECORE_APP_ROOT}/config/runners" \
  "${FORGECORE_APP_ROOT}/state" \
  "${FORGECORE_STORAGE_ROOT}/runners/v2/jojje84-forgecore" \
  "${FORGECORE_STORAGE_ROOT}/runners/jojje84-forgecore" \
  "${FORGECORE_STORAGE_ROOT}/logs" \
  "${FORGECORE_RUNNER_DIST_ROOT}"

cat > "${FORGECORE_APP_ROOT}/config/runners/jojje84-forgecore.env" <<'EOF'
REPOSITORY="Jojje84/ForgeCore"
REGISTRATION_TOKEN=""
EOF

printf '%s\n' '{"AgentId":321,"Ephemeral":false}' > "${FORGECORE_STORAGE_ROOT}/runners/v2/jojje84-forgecore/.runner"
printf '%s\n' 'live-credentials' > "${FORGECORE_STORAGE_ROOT}/runners/v2/jojje84-forgecore/.credentials"
printf '%s\n' '{"AgentId":99,"Ephemeral":false}' > "${FORGECORE_STORAGE_ROOT}/runners/jojje84-forgecore/.runner"
printf '%s\n' 'old-credentials' > "${FORGECORE_STORAGE_ROOT}/runners/jojje84-forgecore/.credentials"
printf '%s\n' "2" > "${FORGECORE_APP_ROOT}/state/runner-engine-v2.initialized"

source "${MANAGER}"

direct="${tmp}/direct-runner"
mkdir -p "${direct}"
prepare_real_workdir "${direct}"
test -d "${direct}/_work"

initialize_runner_layout

target="${FORGECORE_STORAGE_ROOT}/runners/jojje84-forgecore"
test -f "${target}/.runner"
jq -e '.AgentId == 321 and .Ephemeral == false' "${target}/.runner" >/dev/null
grep -Fq 'live-credentials' "${target}/.credentials"
test ! -d "${FORGECORE_STORAGE_ROOT}/runners/v2/jojje84-forgecore"
test -f "${FORGECORE_APP_ROOT}/state/runner-layout-standard.initialized"
test ! -f "${FORGECORE_APP_ROOT}/state/runner-engine-v2.initialized"

backup="$(find "${FORGECORE_STORAGE_ROOT}/runner-backups" -mindepth 1 -maxdepth 1 -type d -name 'jojje84-forgecore-pre-standard-*' | head -n 1)"
test -n "${backup}"
jq -e '.AgentId == 99' "${backup}/.runner" >/dev/null
grep -Fq 'old-credentials' "${backup}/.credentials"

echo "ForgeCore standard runner-layout migration tests: OK"
