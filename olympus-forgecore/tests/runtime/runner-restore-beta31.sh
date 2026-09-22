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
export FORGECORE_RUNNER_DIST_ROOT="${tmp}/dist"

mkdir -p \
  "${FORGECORE_APP_ROOT}/config/runners" \
  "${FORGECORE_APP_ROOT}/state" \
  "${FORGECORE_STORAGE_ROOT}/runners/jojje84-forgecore" \
  "${FORGECORE_STORAGE_ROOT}/logs" \
  "${FORGECORE_RUNNER_DIST_ROOT}"

cat > "${FORGECORE_APP_ROOT}/config/runners/jojje84-forgecore.env" <<'EOF'
REPOSITORY="Jojje84/ForgeCore"
REGISTRATION_TOKEN=""
EOF

printf '%s\n' '{"AgentId":731,"Ephemeral":false}' > "${FORGECORE_STORAGE_ROOT}/runners/jojje84-forgecore/.runner"
printf '%s\n' 'standard-layout-credentials' > "${FORGECORE_STORAGE_ROOT}/runners/jojje84-forgecore/.credentials"

source "${PACKAGE_ROOT}/data/bin/runner-manager.sh"
restore_beta31_runner_layout

target="${FORGECORE_STORAGE_ROOT}/runners/v2/jojje84-forgecore"
test -f "${target}/.runner"
test -f "${target}/.credentials"
jq -e '.AgentId == 731 and .Ephemeral == false' "${target}/.runner" >/dev/null
grep -Fq 'standard-layout-credentials' "${target}/.credentials"

# The beta32+ copy must remain untouched so recovery is non-destructive.
jq -e '.AgentId == 731' "${FORGECORE_STORAGE_ROOT}/runners/jojje84-forgecore/.runner" >/dev/null
grep -Fq 'standard-layout-credentials' "${FORGECORE_STORAGE_ROOT}/runners/jojje84-forgecore/.credentials"

test -f "${FORGECORE_APP_ROOT}/state/runner-engine-v2.initialized"
test "$(cat "${FORGECORE_APP_ROOT}/state/runner-engine-v2.initialized")" = "2"

echo "ForgeCore beta31 layout recovery: OK"
