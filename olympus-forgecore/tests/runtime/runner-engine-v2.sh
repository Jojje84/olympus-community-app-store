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
mkdir -p "${FORGECORE_APP_ROOT}/config/runners" "${FORGECORE_APP_ROOT}/state" \
  "${FORGECORE_STORAGE_ROOT}/runners/jojje84-forgecore" "${FORGECORE_STORAGE_ROOT}/runners/v2" \
  "${FORGECORE_STORAGE_ROOT}/logs" "${FORGECORE_RUNNER_DIST_ROOT}"
printf '%s\n' '{"AgentId":99,"Ephemeral":false}' > "${FORGECORE_STORAGE_ROOT}/runners/jojje84-forgecore/.runner"
cat > "${FORGECORE_APP_ROOT}/config/runners/jojje84-forgecore.env" <<'EOF'
REPOSITORY="Jojje84/ForgeCore"
REGISTRATION_TOKEN="stale-beta-token"
EOF
source "${MANAGER}"
initialize_runner_engine_v2
grep -Fq 'REGISTRATION_TOKEN=""' "${FORGECORE_APP_ROOT}/config/runners/jojje84-forgecore.env"
test -f "${FORGECORE_STORAGE_ROOT}/runners/jojje84-forgecore/.runner"
test ! -f "${FORGECORE_STORAGE_ROOT}/runners/v2/jojje84-forgecore/.runner"
test -f "${FORGECORE_APP_ROOT}/state/runner-engine-v2.initialized"
jq -e '.phase == "needs-repair" and .mode == "rebuilt"' "${FORGECORE_APP_ROOT}/state/runner-jojje84-forgecore.runtime.json" >/dev/null
grep -Fq 'one fresh GitHub registration token' "${FORGECORE_APP_ROOT}/state/runner-jojje84-forgecore.error"
echo "ForgeCore clean runner-engine migration tests: OK"
