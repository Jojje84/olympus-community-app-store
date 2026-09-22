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
export FORGECORE_STORAGE_RESOLUTION="ci-container-boot"

compose=(docker compose -f "${PACKAGE_ROOT}/docker-compose.yml" -p forgecore-boot-test)

cleanup() {
  "${compose[@]}" logs --no-color runner || true
  "${compose[@]}" down -v || true
  sudo rm -rf "${tmp}" || true
}
trap cleanup EXIT

"${compose[@]}" up -d docker runner

for _ in $(seq 1 60); do
  if [[ -s "${app_dir}/data/state/status.json" ]]; then
    now="$(date +%s)"
    last="$(jq -r '.status_epoch // 0' "${app_dir}/data/state/status.json")"
    if [[ "${last}" =~ ^[0-9]+$ ]] && (( now - last < 20 )); then
      expected="$(cat "${PACKAGE_ROOT}/upstream-release.txt")"
      jq -e --arg expected "${expected}" '.runtime_version == $expected' "${app_dir}/data/state/status.json" >/dev/null
      if [[ -f "${app_dir}/data/state/runner-service.error" ]]; then
        echo "unexpected runner-service.error:" >&2
        cat "${app_dir}/data/state/runner-service.error" >&2
        exit 1
      fi
      echo "ForgeCore runner container boot heartbeat: OK"
      exit 0
    fi
  fi
  sleep 2
done

echo "ForgeCore runner container never produced a live heartbeat" >&2
"${compose[@]}" ps >&2 || true
if [[ -f "${app_dir}/data/state/runner-service.error" ]]; then
  echo "runner-service.error:" >&2
  cat "${app_dir}/data/state/runner-service.error" >&2
fi
exit 1
