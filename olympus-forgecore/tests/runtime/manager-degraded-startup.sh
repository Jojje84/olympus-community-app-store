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
mkdir -p "${app_dir}/data/state" "${storage_dir}"
touch "${storage_dir}/.forgecore-external"
cp "${PACKAGE_ROOT}/runner-manager.b64.template" "${app_dir}/runner-manager.b64"

export APP_DATA_DIR="${app_dir}"
export FORGECORE_STORAGE_ROOT="${storage_dir}"
export FORGECORE_STORAGE_RESOLUTION="ci-degraded-start"

compose=(docker compose -f "${PACKAGE_ROOT}/docker-compose.yml" -p forgecore-degraded-start)

cleanup() {
  "${compose[@]}" logs --no-color runner || true
  "${compose[@]}" down -v || true
  sudo rm -rf "${tmp}" || true
}
trap cleanup EXIT

# Start runner without its Docker dependency. The manager must still become
# healthy and process listener reload requests instead of hanging in preflight.
"${compose[@]}" up -d --no-deps runner

ready=false
for _ in $(seq 1 30); do
  if [[ -s "${app_dir}/data/state/status.json" ]]; then
    now="$(date +%s)"
    last="$(jq -r '.status_epoch // 0' "${app_dir}/data/state/status.json")"
    if [[ "${last}" =~ ^[0-9]+$ ]] && (( now - last < 20 )); then
      ready=true
      break
    fi
  fi
  sleep 1
done

if [[ "${ready}" != true ]]; then
  echo "runner manager did not become healthy without Docker dependency" >&2
  exit 1
fi

test ! -f "${app_dir}/data/state/runner-service.error"
test -s "${app_dir}/data/state/dependencies.error"
jq -e '.docker_online == false and .compose_online == false' "${app_dir}/data/state/status.json" >/dev/null
grep -Fq 'control plane ready' "${storage_dir}/logs/runner-manager.log"
echo "ForgeCore manager starts independently of Docker preflight: OK"

before="$(jq -r '.manager_started_epoch' "${app_dir}/data/state/status.json")"
sleep 2
touch "${app_dir}/data/state/reload-runners.request"

reloaded=false
for _ in $(seq 1 15); do
  after="$(jq -r '.manager_started_epoch // 0' "${app_dir}/data/state/status.json" 2>/dev/null || echo 0)"
  if [[ "${after}" =~ ^[0-9]+$ ]] && (( after > before )); then
    reloaded=true
    break
  fi
  sleep 1
done

test "${reloaded}" = true
grep -Fq 'Dashboard requested runner reload' "${storage_dir}/logs/runner-manager.log"
echo "ForgeCore listener reload remains available during degraded dependencies: OK"
