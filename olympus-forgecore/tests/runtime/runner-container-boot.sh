#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -d "${ROOT}/umbrel" ]]; then
  PACKAGE_ROOT="${ROOT}/umbrel"
else
  PACKAGE_ROOT="${ROOT}"
fi

tmp="$(mktemp -d)"
app_dir="${tmp}/app"
storage_dir="${tmp}/storage"
mkdir -p "${app_dir}/data/state" "${storage_dir}/logs" "${storage_dir}/runners" "${storage_dir}/cache" "${storage_dir}/workspaces" "${storage_dir}/artifacts" "${storage_dir}/runner-backups"
touch "${storage_dir}/.forgecore-external"

# Simulate Umbrel's template_app(): installed *.template files are rendered to
# the same filename with .template stripped before Compose starts.
cp "${PACKAGE_ROOT}/runner-manager.b64.template" "${app_dir}/runner-manager.b64"
cp "${PACKAGE_ROOT}/dashboard-server.b64.template" "${app_dir}/dashboard-server.b64"
cp "${PACKAGE_ROOT}/cleanup-loop.b64.template" "${app_dir}/cleanup-loop.b64"

# Reproduce umbrelOS ownership: app data may be root-owned while the official
# actions-runner image starts as uid 1001. ForgeCore bootstrap must repair this.
sudo chown -R root:root "${app_dir}/data" "${storage_dir}/logs" "${storage_dir}/runners" "${storage_dir}/cache" "${storage_dir}/workspaces" "${storage_dir}/artifacts" "${storage_dir}/runner-backups"
sudo chmod -R u+rwX,go+rX "${app_dir}/data" "${storage_dir}/logs" "${storage_dir}/runners" "${storage_dir}/cache" "${storage_dir}/workspaces" "${storage_dir}/artifacts" "${storage_dir}/runner-backups"

export APP_DATA_DIR="${app_dir}"
export FORGECORE_STORAGE_ROOT="${storage_dir}"
export FORGECORE_STORAGE_RESOLUTION="ci-container-boot"

compose=(docker compose -f "${PACKAGE_ROOT}/docker-compose.yml" -p forgecore-boot-test)

cleanup() {
  "${compose[@]}" logs --no-color runner || true
  "${compose[@]}" down -v || true
  sudo rm -rf "${tmp}" || true
}
trap cleanup EXIT

"${compose[@]}" up -d docker runner web

boot_ok=false
for _ in $(seq 1 60); do
  if [[ -s "${app_dir}/data/state/status.json" ]]; then
    now="$(date +%s)"
    last="$(jq -r '.status_epoch // 0' "${app_dir}/data/state/status.json")"
    if [[ "${last}" =~ ^[0-9]+$ ]] && (( now - last < 20 )); then
      expected="$(cat "${PACKAGE_ROOT}/upstream-release.txt")"
      jq -e --arg expected "${expected}" --arg build "0.1.0-beta.36" '.runtime_version == $expected and .manager_build == $build' "${app_dir}/data/state/status.json" >/dev/null
      if [[ -f "${app_dir}/data/state/runner-service.error" ]]; then
        echo "unexpected runner-service.error:" >&2
        cat "${app_dir}/data/state/runner-service.error" >&2
        exit 1
      fi
      grep -Fq 'ForgeCore 0.1.0-beta.36 runner bootstrap started' "${app_dir}/data/state/runner-bootstrap.log"
      grep -Fq 'manager artifact verified; launching' "${app_dir}/data/state/runner-bootstrap.log"
      test "$(stat -c %u "${app_dir}/data/state")" = "1001"
      echo "ForgeCore root-owned app-data bootstrap recovery: OK"
      echo "ForgeCore runner container boot heartbeat: OK"
      grep -Fq 'RUNNER_ENGINE_ROOT="${STORAGE_ROOT}/runners"' "${PACKAGE_ROOT}/data/bin/runner-manager.sh"
      boot_ok=true
      break
    fi
  fi
  sleep 2
done

if [[ "${boot_ok}" != true ]]; then
  echo "ForgeCore runner container never produced a live heartbeat" >&2
  "${compose[@]}" ps >&2 || true
  if [[ -f "${app_dir}/data/state/runner-service.error" ]]; then
    echo "runner-service.error:" >&2
    cat "${app_dir}/data/state/runner-service.error" >&2
  fi
  exit 1
fi

for _ in $(seq 1 30); do
  if health_json="$(curl -fsS http://127.0.0.1:8799/health)"
jq -e '.manager_artifact_ok == true and .manager_artifact_build == "0.1.0-beta.36" and .bootstrap_beta36_seen == true' <<< "${health_json}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl -fsS http://127.0.0.1:8799/health >/dev/null

# Reproduce the live Umbrel Repair handoff exactly: the web container is root,
# while runner-manager runs as the actions-runner user. Pause the manager so it
# cannot consume the request while we validate the web/API safety contract.
"${compose[@]}" pause runner

config_dir="${app_dir}/data/config/runners"
config_file="${config_dir}/jojje84-forgecore.env"
runner_dir="${storage_dir}/runners/jojje84-forgecore"
mkdir -p "${runner_dir}"
printf '%s\n' '{"AgentId":777,"Ephemeral":false}' > "${runner_dir}/.runner"
printf '%s\n' 'protected-ci-credentials' > "${runner_dir}/.credentials"

status="$(curl -sS -o "${tmp}/guard-response.json" -w '%{http_code}' -X POST \
  -H 'Content-Type: application/json' \
  --data '{"repository":"Jojje84/ForgeCore","token":"accidental-ci-registration-token-1234567890"}' \
  http://127.0.0.1:8799/api/runners)"
test "${status}" = "409"
grep -Fq 'No changes were made' "${tmp}/guard-response.json"
jq -e '.AgentId == 777' "${runner_dir}/.runner" >/dev/null
grep -Fq 'protected-ci-credentials' "${runner_dir}/.credentials"
test ! -f "${config_file}"
echo "ForgeCore dashboard accidental Repair guard: OK"

curl -fsS -X POST \
  -H 'Content-Type: application/json' \
  --data '{"repository":"Jojje84/ForgeCore","token":"invalid-ci-registration-token-1234567890","repair_existing":true}' \
  http://127.0.0.1:8799/api/runners >/dev/null

test -f "${config_file}"
test "$(stat -c %a "${config_file}")" = "600"
test "$(stat -c %u:%g "${config_file}")" = "$(stat -c %u:%g "${config_dir}")"
grep -Fq 'REPAIR_EXISTING="true"' "${config_file}"
echo "ForgeCore dashboard preserved runner config ownership: OK"

"${compose[@]}" unpause runner

registration_log="${storage_dir}/logs/registration-jojje84-forgecore.log"
for _ in $(seq 1 30); do
  if [[ -s "${registration_log}" ]] && grep -Fq 'registration started for Jojje84/ForgeCore' "${registration_log}"; then
    grep -Fq 'Dashboard requested runner reload' "${storage_dir}/logs/runner-manager.log"
    echo "ForgeCore cross-container confirmed Repair handoff: OK"
    exit 0
  fi
  sleep 1
done

echo "Repair signal reached the dashboard but runner-manager never started registration" >&2
"${compose[@]}" logs --no-color runner >&2 || true
exit 1
