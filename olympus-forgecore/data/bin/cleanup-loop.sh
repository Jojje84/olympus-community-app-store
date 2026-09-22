#!/bin/sh
set -eu

APP_ROOT="${FORGECORE_APP_ROOT:-/forgecore/app}"
STORAGE_ROOT="${FORGECORE_STORAGE_ROOT:-/forgecore/storage}"
CONFIG_FILE="${APP_ROOT}/config/forgecore.env"
STATE_DIR="${APP_ROOT}/state"
LOG_FILE="${STORAGE_ROOT}/logs/cleanup.log"
LAST_RUN_FILE="${STATE_DIR}/last-cleanup-epoch"
RUN_NOW_FILE="${STATE_DIR}/cleanup-now.request"

log() { printf '[forgecore-cleanup] %s\n' "$*" | tee -a "${LOG_FILE}"; }

load_config() {
  CLEANUP_INTERVAL_HOURS=168
  CACHE_MAX_AGE_DAYS=14
  WORKSPACE_MAX_AGE_DAYS=30
  DISK_CLEANUP_THRESHOLD_PERCENT=85
  BUILDKIT_KEEP_STORAGE_GB=50
  if [ -f "${CONFIG_FILE}" ]; then . "${CONFIG_FILE}"; fi
}

wait_for_docker() {
  i=0
  until docker info >/dev/null 2>&1; do
    i=$((i + 1))
    [ "${i}" -lt 60 ] || return 1
    sleep 2
  done
}

prune_workspace_contents() {
  if [ -d "${STORAGE_ROOT}/runners" ]; then
    for workspace_root in "${STORAGE_ROOT}"/runners/*/_work; do
      [ -d "${workspace_root}" ] || continue
      find "${workspace_root}" -mindepth 1 -maxdepth 1 -mtime "+${WORKSPACE_MAX_AGE_DAYS}" -exec rm -rf '{}' ';' || true
    done
  fi

  # beta.8 legacy workspace location.
  if [ -d "${STORAGE_ROOT}/workspaces" ]; then
    for workspace_root in "${STORAGE_ROOT}"/workspaces/*; do
      [ -d "${workspace_root}" ] || continue
      find "${workspace_root}" -mindepth 1 -maxdepth 1 -mtime "+${WORKSPACE_MAX_AGE_DAYS}" -exec rm -rf '{}' ';' || true
    done
  fi
}

prune_artifacts() {
  [ -d "${STORAGE_ROOT}/artifacts" ] || return 0
  find "${STORAGE_ROOT}/artifacts" -mindepth 1 -mtime "+${WORKSPACE_MAX_AGE_DAYS}" -exec rm -rf '{}' ';' || true
}

run_cleanup() {
  load_config
  now="$(date +%s)"
  age_hours=$((CACHE_MAX_AGE_DAYS * 24))

  log "cleanup started"
  docker container prune -f --filter "until=${age_hours}h" >>"${LOG_FILE}" 2>&1 || true
  docker image prune -f --filter "until=${age_hours}h" >>"${LOG_FILE}" 2>&1 || true
  docker builder prune -f --filter "until=${age_hours}h" --keep-storage "${BUILDKIT_KEEP_STORAGE_GB}GB" >>"${LOG_FILE}" 2>&1 || true

  prune_workspace_contents
  prune_artifacts

  usage="$(df -P "${STORAGE_ROOT}" | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
  if [ "${usage:-0}" -ge "${DISK_CLEANUP_THRESHOLD_PERCENT}" ]; then
    log "disk pressure threshold reached at ${usage}%"
    docker builder prune -f --filter "until=${age_hours}h" --keep-storage "${BUILDKIT_KEEP_STORAGE_GB}GB" >>"${LOG_FILE}" 2>&1 || true
  fi

  printf '%s\n' "${now}" > "${LAST_RUN_FILE}"
  rm -f "${RUN_NOW_FILE}"
  log "cleanup completed"
}

mkdir -p "${STATE_DIR}" "${STORAGE_ROOT}/logs"
wait_for_docker

while true; do
  load_config
  now="$(date +%s)"
  last=0
  if [ -f "${LAST_RUN_FILE}" ]; then last="$(cat "${LAST_RUN_FILE}" 2>/dev/null || echo 0)"; fi
  due=$((CLEANUP_INTERVAL_HOURS * 3600))

  if [ -f "${RUN_NOW_FILE}" ] || [ $((now - last)) -ge "${due}" ]; then
    run_cleanup
  fi
  sleep 10
done
