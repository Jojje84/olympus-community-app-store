#!/bin/sh
set -eu

APP_ROOT="${FORGECORE_APP_ROOT:-/forgecore/app}"
STORAGE_ROOT="${FORGECORE_STORAGE_ROOT:-/forgecore/storage}"
GLOBAL_CONFIG="${APP_ROOT}/config/global.json"
STATE_DIR="${APP_ROOT}/state"
LOG_FILE="${STORAGE_ROOT}/logs/cleanup.log"
LAST_RUN_FILE="${STATE_DIR}/last-cleanup-epoch"
RUN_NOW_FILE="${STATE_DIR}/cleanup-now.request"
RUNNING_FILE="${STATE_DIR}/cleanup-running"
ACTIVITY_FILE="${STATE_DIR}/activity.log"

log() { printf '[forgecore-cleanup] %s\n' "$*" | tee -a "${LOG_FILE}"; }

activity() {
  kind="$1"
  message="$2"
  epoch="$(date +%s)"
  printf '{"epoch":%s,"type":"%s","message":"%s"}\n' "${epoch}" "${kind}" "${message}" >> "${ACTIVITY_FILE}" || true
}

json_int() {
  key="$1"
  fallback="$2"
  [ -f "${GLOBAL_CONFIG}" ] || { printf '%s\n' "${fallback}"; return 0; }
  value="$(sed -n -E 's/.*"'"'"'"${key}"'"'"'"[[:space:]]*:[[:space:]]*([0-9]+).*/\1/p' "${GLOBAL_CONFIG}" | head -n 1)"
  case "${value}" in
    ''|*[!0-9]*) printf '%s\n' "${fallback}" ;;
    *) printf '%s\n' "${value}" ;;
  esac
}

load_config() {
  CLEANUP_INTERVAL_HOURS="$(json_int intervalHours 168)"
  CACHE_MAX_AGE_DAYS="$(json_int cacheMaxAgeDays 14)"
  WORKSPACE_MAX_AGE_DAYS="$(json_int workspaceMaxAgeDays 30)"
  DISK_CLEANUP_THRESHOLD_PERCENT="$(json_int diskThresholdPercent 85)"
  BUILDKIT_KEEP_STORAGE_GB="$(json_int buildkitKeepStorageGB 50)"
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

  # Native v2 executor workspaces.
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
  age_hours=$((CACHE_MAX_AGE_DAYS * 24))
  : > "${RUNNING_FILE}"

  log "cleanup started"
  activity "cleanup" "Cleanup started"
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

  finished="$(date +%s)"
  printf '%s\n' "${finished}" > "${LAST_RUN_FILE}"
  rm -f "${RUN_NOW_FILE}" "${RUNNING_FILE}"
  log "cleanup completed"
  activity "cleanup" "Cleanup completed"
}

cleanup_exit() { rm -f "${RUNNING_FILE}"; }
trap cleanup_exit EXIT
trap 'exit 0' INT TERM

mkdir -p "${STATE_DIR}" "${STORAGE_ROOT}/logs"
rm -f "${RUNNING_FILE}"
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
