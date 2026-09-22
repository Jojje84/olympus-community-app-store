#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -d "${ROOT}/umbrel" ]]; then
  PACKAGE_ROOT="${ROOT}/umbrel"
else
  PACKAGE_ROOT="${ROOT}"
fi

EXPORTS_FILE="${PACKAGE_ROOT}/exports.sh"
COMPOSE_FILE="${PACKAGE_ROOT}/docker-compose.yml"

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

umbrel_root="${tmp}/umbrel"
app_dir="${umbrel_root}/app-data/olympus-forgecore"
external_root="${umbrel_root}/external/HDD/ForgeCore"
mkdir -p "${app_dir}/data/state" "${external_root}"
touch "${external_root}/.forgecore-external"

# Simulate the variables Umbrel exposes before sourcing app exports.sh.
export UMBREL_ROOT="${umbrel_root}"
export EXPORTS_APP_DIR="${app_dir}"
export EXPORTS_APP_DATA_DIR="${app_dir}/data"
unset FORGECORE_STORAGE_ROOT FORGECORE_STORAGE_RESOLUTION || true

# A legacy/manual external path must be rediscovered automatically.
# shellcheck source=/dev/null
source "${EXPORTS_FILE}"
test "${FORGECORE_STORAGE_ROOT}" = "${external_root}"
test "${FORGECORE_STORAGE_RESOLUTION}" = "external-discovery"
test "$(cat "${app_dir}/data/forgecore-storage-root")" = "${external_root}"
test ! -e "${app_dir}/data/state/storage-resolution.error"

# Compose must bind every ForgeCore storage consumer to the resolved host path.
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  export APP_DATA_DIR="${app_dir}"
  docker compose -f "${COMPOSE_FILE}" config > "${tmp}/compose-resolved.yml"
  grep -Fq "${external_root}:/forgecore/storage" "${tmp}/compose-resolved.yml"
fi

# A saved verified path must survive package updates without rediscovery.
unset FORGECORE_STORAGE_ROOT FORGECORE_STORAGE_RESOLUTION || true
# shellcheck source=/dev/null
source "${EXPORTS_FILE}"
test "${FORGECORE_STORAGE_ROOT}" = "${external_root}"
test "${FORGECORE_STORAGE_RESOLUTION}" = "saved"

# An explicit verified path takes precedence.
explicit_root="${umbrel_root}/external/NVME/ForgeCore"
mkdir -p "${explicit_root}"
touch "${explicit_root}/.forgecore-external"
export FORGECORE_STORAGE_ROOT="${explicit_root}"
unset FORGECORE_STORAGE_RESOLUTION || true
# shellcheck source=/dev/null
source "${EXPORTS_FILE}"
test "${FORGECORE_STORAGE_ROOT}" = "${explicit_root}"
test "${FORGECORE_STORAGE_RESOLUTION}" = "environment"
test "$(cat "${app_dir}/data/forgecore-storage-root")" = "${explicit_root}"

# If the saved path disappears and multiple verified roots exist, ForgeCore must
# refuse to guess and must leave a durable error for the dashboard.
rm -f "${app_dir}/data/forgecore-storage-root"
rm -rf "${explicit_root}"
second_root="${umbrel_root}/external/SSD/ForgeCore"
mkdir -p "${second_root}"
touch "${second_root}/.forgecore-external"
third_root="${umbrel_root}/external/NAS/ForgeCore"
mkdir -p "${third_root}"
touch "${third_root}/.forgecore-external"
unset FORGECORE_STORAGE_ROOT FORGECORE_STORAGE_RESOLUTION || true
# shellcheck source=/dev/null
source "${EXPORTS_FILE}"
test "${FORGECORE_STORAGE_ROOT}" = "/mnt/forgecore"
test "${FORGECORE_STORAGE_RESOLUTION}" = "unresolved"
grep -Fq "could not find a verified external storage root" "${app_dir}/data/state/storage-resolution.error"

echo "ForgeCore Umbrel storage-resolution tests: OK"
