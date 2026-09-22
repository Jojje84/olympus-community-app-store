#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -d "${ROOT}/umbrel" ]]; then
  PACKAGE_ROOT="${ROOT}/umbrel"
else
  PACKAGE_ROOT="${ROOT}"
fi

tmp="$(mktemp -d)"
trap 'for p in "${RUNNER_PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done; rm -rf "${tmp}"' EXIT

export FORGECORE_APP_ROOT="${tmp}/app"
export FORGECORE_STORAGE_ROOT="${tmp}/storage"
export FORGECORE_RUNNER_DIST_ROOT="${tmp}/dist"
export FORGECORE_RUNNER_STARTUP_GRACE_SECONDS=1
mkdir -p \
  "${FORGECORE_APP_ROOT}/config/runners" \
  "${FORGECORE_APP_ROOT}/state" \
  "${FORGECORE_STORAGE_ROOT}/runners/jojje84-forgecore" \
  "${FORGECORE_STORAGE_ROOT}/logs" \
  "${FORGECORE_RUNNER_DIST_ROOT}"

cat > "${FORGECORE_RUNNER_DIST_ROOT}/config.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${FAKE_REPAIR_FAIL:-0}" == "1" ]]; then
  echo "simulated GitHub registration failure"
  exit 1
fi
printf '%s\n' '{"AgentId":88,"Ephemeral":false}' > .runner
printf '%s\n' 'replacement-credentials' > .credentials
SH
chmod +x "${FORGECORE_RUNNER_DIST_ROOT}/config.sh"

cat > "${FORGECORE_RUNNER_DIST_ROOT}/run.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
echo "Listening for Jobs"
sleep 60
SH
chmod +x "${FORGECORE_RUNNER_DIST_ROOT}/run.sh"

runner_dir="${FORGECORE_STORAGE_ROOT}/runners/jojje84-forgecore"
cp "${FORGECORE_RUNNER_DIST_ROOT}/run.sh" "${runner_dir}/run.sh"
chmod +x "${runner_dir}/run.sh"
printf '%s\n' '{"AgentId":77,"Ephemeral":false}' > "${runner_dir}/.runner"
printf '%s\n' 'original-credentials' > "${runner_dir}/.credentials"

config="${FORGECORE_APP_ROOT}/config/runners/jojje84-forgecore.env"
cat > "${config}" <<'EOF'
REPOSITORY="Jojje84/ForgeCore"
REGISTRATION_TOKEN="accidental-token-1234567890"
REPAIR_EXISTING="false"
EOF

source "${PACKAGE_ROOT}/data/bin/runner-manager.sh"

start_runner_from_config "${config}"
jq -e '.AgentId == 77 and .Ephemeral == false' "${runner_dir}/.runner" >/dev/null
grep -Fq 'original-credentials' "${runner_dir}/.credentials"
grep -Fq 'REGISTRATION_TOKEN=""' "${config}"
grep -Fq 'REPAIR_EXISTING="false"' "${config}"
test ! -s "${FORGECORE_STORAGE_ROOT}/logs/registration-jojje84-forgecore.log"
grep -Fq 'blocked unconfirmed runner replacement' "${FORGECORE_STORAGE_ROOT}/logs/runner-manager.log"
echo "ForgeCore accidental token guard preserved identity: OK"

stop_runners

cat > "${config}" <<'EOF'
REPOSITORY="Jojje84/ForgeCore"
REGISTRATION_TOKEN="failing-repair-token-1234567890"
REPAIR_EXISTING="true"
EOF

export FAKE_REPAIR_FAIL=1
if start_runner_from_config "${config}"; then
  echo "expected failed confirmed Repair" >&2
  exit 1
fi
unset FAKE_REPAIR_FAIL
jq -e '.AgentId == 77 and .Ephemeral == false' "${runner_dir}/.runner" >/dev/null
grep -Fq 'original-credentials' "${runner_dir}/.credentials"
grep -Fq 'REGISTRATION_TOKEN=""' "${config}"
grep -Fq 'REPAIR_EXISTING="false"' "${config}"
grep -Fq 'Previous runner identity was restored' "${FORGECORE_APP_ROOT}/state/runner-jojje84-forgecore.error"
echo "ForgeCore failed Repair rollback preserved identity: OK"

cat > "${config}" <<'EOF'
REPOSITORY="Jojje84/ForgeCore"
REGISTRATION_TOKEN="confirmed-repair-token-1234567890"
REPAIR_EXISTING="true"
EOF

start_runner_from_config "${config}"
jq -e '.AgentId == 88 and .Ephemeral == false' "${runner_dir}/.runner" >/dev/null
grep -Fq 'replacement-credentials' "${runner_dir}/.credentials"
grep -Fq 'REGISTRATION_TOKEN=""' "${config}"
grep -Fq 'REPAIR_EXISTING="false"' "${config}"
grep -Fq 'registration started for Jojje84/ForgeCore' "${FORGECORE_STORAGE_ROOT}/logs/registration-jojje84-forgecore.log"
echo "ForgeCore confirmed Repair replacement: OK"

stop_runners
