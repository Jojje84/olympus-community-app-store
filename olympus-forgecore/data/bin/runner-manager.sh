#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${FORGECORE_APP_ROOT:-/forgecore/app}"
STORAGE_ROOT="${FORGECORE_STORAGE_ROOT:-/forgecore/storage}"
CONFIG_DIR="${APP_ROOT}/config"
RUNNER_CONFIG_DIR="${CONFIG_DIR}/runners"
STATE_DIR="${APP_ROOT}/state"
CONFIG_FILE="${CONFIG_DIR}/forgecore.env"
RELOAD_FILE="${STATE_DIR}/reload-runners.request"
LOG_FILE="${STORAGE_ROOT}/logs/runner-manager.log"
ACTIVITY_FILE="${STATE_DIR}/activity.log"

declare -a RUNNER_PIDS=()
STATUS_PID=""
MANAGER_STARTED_EPOCH="$(date +%s)"

log() {
  printf '[forgecore] %s\n' "$*"
  if [[ -d "${STORAGE_ROOT}/logs" ]]; then
    printf '%s [forgecore] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "${LOG_FILE}" || true
  fi
}

activity() {
  local kind="$1" message="$2"
  jq -cn --argjson epoch "$(date +%s)" --arg type "${kind}" --arg message "${message}"     '{epoch:$epoch,type:$type,message:$message}' >> "${ACTIVITY_FILE}" || true
}

prepare_paths() {
  sudo mkdir -p "${CONFIG_DIR}" "${RUNNER_CONFIG_DIR}" "${STATE_DIR}"
  sudo mkdir -p "${STORAGE_ROOT}/docker"
  sudo mkdir -p \
    "${STORAGE_ROOT}/runners" \
    "${STORAGE_ROOT}/workspaces" \
    "${STORAGE_ROOT}/cache/docker-config/cli-plugins" \
    "${STORAGE_ROOT}/cache/go-build" \
    "${STORAGE_ROOT}/cache/go-mod" \
    "${STORAGE_ROOT}/cache/npm" \
    "${STORAGE_ROOT}/cache/playwright" \
    "${STORAGE_ROOT}/cache/toolcache" \
    "${STORAGE_ROOT}/artifacts" \
    "${STORAGE_ROOT}/logs"

  sudo chown -R runner:docker "${APP_ROOT}"
  sudo chown -R runner:docker \
    "${STORAGE_ROOT}/runners" \
    "${STORAGE_ROOT}/workspaces" \
    "${STORAGE_ROOT}/cache" \
    "${STORAGE_ROOT}/artifacts" \
    "${STORAGE_ROOT}/logs"

  if [[ ! -f "${CONFIG_FILE}" ]]; then
    cat > "${CONFIG_FILE}" <<'FORGECORE_CONFIG'
# ForgeCore v1 global settings.
CLEANUP_INTERVAL_HOURS=168
CACHE_MAX_AGE_DAYS=14
WORKSPACE_MAX_AGE_DAYS=30
DISK_CLEANUP_THRESHOLD_PERCENT=85
BUILDKIT_KEEP_STORAGE_GB=50
COMPOSE_VERSION="5.5.1"
COMPOSE_SHA256_X86_64="db1889184726840f75c4f9c001048430d4f25b3be3cb084d3ddd762bc0aed576"
COMPOSE_SHA256_AARCH64="732e3a84c1a0f67256ce80bc2598a24546b10ca05f9faa97efceb1171ece2ef7"
FORGECORE_CONFIG
    chmod 600 "${CONFIG_FILE}"
  fi

  # This is only an example/fallback file, so refresh it on every startup.
  # Real repository configs are separate *.env files and are never overwritten here.
  cat > "${RUNNER_CONFIG_DIR}/runner.env.example" <<'FORGECORE_RUNNER_CONFIG'
# One file per GitHub repository.
# Prefer the ForgeCore dashboard for normal setup.
# Manual fallback: copy this file to a new .env file in this directory.
# ForgeCore derives runner name and its single custom label from REPOSITORY.
REPOSITORY=""
REGISTRATION_TOKEN=""
FORGECORE_RUNNER_CONFIG
  chmod 600 "${RUNNER_CONFIG_DIR}/runner.env.example"
}

load_config() {
  source "${CONFIG_FILE}"
  : "${COMPOSE_VERSION:=5.5.1}"
  : "${COMPOSE_SHA256_X86_64:=db1889184726840f75c4f9c001048430d4f25b3be3cb084d3ddd762bc0aed576}"
  : "${COMPOSE_SHA256_AARCH64:=732e3a84c1a0f67256ce80bc2598a24546b10ca05f9faa97efceb1171ece2ef7}"
  : "${CLEANUP_INTERVAL_HOURS:=168}"
  : "${CACHE_MAX_AGE_DAYS:=14}"
}

wait_for_docker() {
  log "waiting for isolated Docker engine"
  for _ in $(seq 1 60); do
    if docker info >/dev/null 2>&1; then
      log "isolated Docker engine is ready"
      return 0
    fi
    sleep 2
  done
  log "Docker engine did not become ready"
  return 1
}

install_compose() {
  local plugin_dir="${DOCKER_CONFIG:-/home/runner/.docker}/cli-plugins"
  local plugin="${plugin_dir}/docker-compose"
  local machine compose_arch compose_sha
  machine="$(uname -m)"
  case "${machine}" in
    x86_64|amd64) compose_arch="x86_64"; compose_sha="${COMPOSE_SHA256_X86_64}" ;;
    aarch64|arm64) compose_arch="aarch64"; compose_sha="${COMPOSE_SHA256_AARCH64}" ;;
    *) log "unsupported architecture for Docker Compose: ${machine}"; return 1 ;;
  esac
  mkdir -p "${plugin_dir}"
  if [[ -x "${plugin}" ]] && "${plugin}" version >/dev/null 2>&1; then return 0; fi
  log "installing Docker Compose v${COMPOSE_VERSION} for ${compose_arch}"
  curl -fsSL --retry 3 "https://github.com/docker/compose/releases/download/v${COMPOSE_VERSION}/docker-compose-linux-${compose_arch}" -o "${plugin}.tmp"
  printf '%s  %s\n' "${compose_sha}" "${plugin}.tmp" | sha256sum -c -
  mv "${plugin}.tmp" "${plugin}"
  chmod +x "${plugin}"
}

slugify() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's#[^a-z0-9]+#-#g; s#^-+##; s#-+$##'
}

copy_runner_distribution() {
  local destination="$1" item
  for item in /home/runner/* /home/runner/.[!.]* /home/runner/..?*; do
    [[ -e "${item}" ]] || continue
    [[ "$(basename "${item}")" == ".docker" ]] && continue
    cp -a "${item}" "${destination}/"
  done
}

clear_registration_token() {
  local file="$1"
  sed -i -E 's/^[[:space:]]*REGISTRATION_TOKEN=.*/REGISTRATION_TOKEN=""/' "${file}"
  chmod 600 "${file}"
}

prepare_real_workdir() {
  local runner_dir="$1" work_dir="${runner_dir}/_work"
  if [[ -L "${work_dir}" ]]; then
    log "migrating ${work_dir} from symlink to real directory"
    rm -f "${work_dir}"
  fi
  mkdir -p "${work_dir}"
}

start_runner_from_config() {
  local config_file="$1"
  local REPOSITORY="" REGISTRATION_TOKEN="" NAME="" LABELS=""
  local repo slug repo_label runner_dir runner_name labels pid error_file runner_log

  source "${config_file}"
  repo="${REPOSITORY}"

  [[ -n "${repo}" ]] || return 0
  [[ "${repo}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || { log "invalid repository in ${config_file}: ${repo}"; return 1; }

  slug="$(slugify "${repo}")"
  repo_label="${repo##*/}"
  labels="${repo_label}"

  runner_dir="${STORAGE_ROOT}/runners/${slug}"
  runner_name="${repo_label:0:63}"
  error_file="${STATE_DIR}/runner-${slug}.error"
  runner_log="${STORAGE_ROOT}/logs/runner-${slug}.log"

  mkdir -p "${runner_dir}"
  if [[ ! -x "${runner_dir}/run.sh" ]]; then
    log "initializing runner files for ${repo}"
    copy_runner_distribution "${runner_dir}"
  fi

  prepare_real_workdir "${runner_dir}"
  rm -f "${error_file}"
  printf '%s\n' "${runner_name}" > "${STATE_DIR}/runner-${slug}.name"
  printf '%s\n' "${repo}" > "${STATE_DIR}/runner-${slug}.repo"

  # Supplying a fresh token from the dashboard means explicit registration/repair.
  # Clear only the local runner identity files; --replace then refreshes the same
  # named runner at GitHub. Workspaces, caches and repository config are kept.
  if [[ -n "${REGISTRATION_TOKEN}" && -f "${runner_dir}/.runner" ]]; then
    log "refreshing runner registration for ${repo}"
    rm -f \
      "${runner_dir}/.runner" \
      "${runner_dir}/.credentials" \
      "${runner_dir}/.credentials_rsaparams" \
      "${runner_dir}/.credentials_migrated" \
      "${runner_dir}/.service"
  fi

  if [[ ! -f "${runner_dir}/.runner" ]]; then
    if [[ -z "${REGISTRATION_TOKEN}" ]]; then
      printf '%s\n' "Waiting for a GitHub registration token" > "${error_file}"
      return 0
    fi
    log "registering runner for ${repo}"
    if ! (
      cd "${runner_dir}"
      ./config.sh --unattended --replace --url "https://github.com/${repo}" --token "${REGISTRATION_TOKEN}" --name "${runner_name}" --work "_work" --labels "${labels}"
    ); then
      clear_registration_token "${config_file}"
      printf '%s\n' "Registration failed. Generate a fresh GitHub runner token and try again." > "${error_file}"
      return 1
    fi
    clear_registration_token "${config_file}"
    activity "runner" "Runner registered for ${repo}"
  elif [[ -n "${REGISTRATION_TOKEN}" ]]; then
    clear_registration_token "${config_file}"
  fi

  log "starting ${runner_name}"
  printf '%s runner starting: %s (%s)\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${runner_name}" "${repo}" >> "${runner_log}"
  ( cd "${runner_dir}" && exec ./run.sh ) >> "${runner_log}" 2>&1 &
  pid=$!
  printf '%s\n' "${pid}" > "${STATE_DIR}/runner-${slug}.pid"
  printf '%s\n' "1" > "${STATE_DIR}/runner-${slug}.online"
  RUNNER_PIDS+=("${pid}")
  activity "runner" "Runner online: ${repo}"
}

write_status() {
  local docker_online=false configured=0 online=0 disk_total="—" disk_used="—" disk_pct=0 runner_summary="Runner not configured"
  local repo_file slug pid_file pid

  docker info >/dev/null 2>&1 && docker_online=true

  shopt -s nullglob
  local repo_files=("${STATE_DIR}"/runner-*.repo)
  configured="${#repo_files[@]}"
  for repo_file in "${repo_files[@]}"; do
    slug="${repo_file##*/runner-}"; slug="${slug%.repo}"
    pid_file="${STATE_DIR}/runner-${slug}.pid"
    [[ -f "${pid_file}" ]] || continue
    pid="$(cat "${pid_file}" 2>/dev/null || true)"
    [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null && online=$((online + 1))
  done
  shopt -u nullglob

  (( configured > 0 )) && runner_summary="${online}/${configured} runner(s) online"

  if df -Pk "${STORAGE_ROOT}" >/dev/null 2>&1; then
    disk_pct="$(df -Pk "${STORAGE_ROOT}" | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
    disk_total="$(df -hP "${STORAGE_ROOT}" | awk 'NR==2 {print $2}')"
    disk_used="$(df -hP "${STORAGE_ROOT}" | awk 'NR==2 {print $3}')"
  fi

  jq -n \
    --argjson runner_online "$([[ "${online}" -gt 0 ]] && echo true || echo false)" \
    --arg runner_name "${runner_summary}" \
    --argjson docker_online "${docker_online}" \
    --argjson compose_online true \
    --arg disk_used "${disk_used}" \
    --arg disk_total "${disk_total}" \
    --argjson disk_used_percent "${disk_pct:-0}" \
    --arg disk_path "${STORAGE_ROOT}" \
    --argjson cleanup_interval_days "$((CLEANUP_INTERVAL_HOURS / 24))" \
    --argjson cache_max_age_days "${CACHE_MAX_AGE_DAYS}" \
    --argjson manager_started_epoch "${MANAGER_STARTED_EPOCH}" \
    --argjson status_epoch "$(date +%s)" \
    '{runner_online:$runner_online,runner_name:$runner_name,docker_online:$docker_online,compose_online:$compose_online,disk_used:$disk_used,disk_total:$disk_total,disk_used_percent:$disk_used_percent,disk_path:$disk_path,cleanup_interval_days:$cleanup_interval_days,cache_max_age_days:$cache_max_age_days,manager_started_epoch:$manager_started_epoch,status_epoch:$status_epoch}' \
    > "${STATE_DIR}/status.json.tmp"
  mv "${STATE_DIR}/status.json.tmp" "${STATE_DIR}/status.json"
}

status_loop() { while true; do write_status || true; sleep 5; done; }

stop_runners() {
  local pid
  if (( ${#RUNNER_PIDS[@]} > 0 )); then
    for pid in "${RUNNER_PIDS[@]}"; do
      [[ -n "${pid}" ]] && kill "${pid}" 2>/dev/null || true
    done
    for pid in "${RUNNER_PIDS[@]}"; do
      [[ -n "${pid}" ]] && wait "${pid}" 2>/dev/null || true
    done
  fi
  RUNNER_PIDS=()
  rm -f "${STATE_DIR}"/runner-*.pid "${STATE_DIR}"/runner-*.online
}

start_all_runners() {
  local config_file
  rm -f "${STATE_DIR}"/runner-*.pid "${STATE_DIR}"/runner-*.name "${STATE_DIR}"/runner-*.repo "${STATE_DIR}"/runner-*.online

  shopt -s nullglob
  local runner_configs=("${RUNNER_CONFIG_DIR}"/*.env)
  shopt -u nullglob

  for config_file in "${runner_configs[@]}"; do
    [[ "$(basename "${config_file}")" == "runner.env.example" ]] && continue
    start_runner_from_config "${config_file}" || true
  done

  if (( ${#RUNNER_PIDS[@]} == 0 )); then
    log "No runner is ready. Add or repair one from the ForgeCore dashboard."
  fi
}

reload_runners() {
  local reason="${1:-runner reload requested}"
  log "${reason}"
  activity "runner" "${reason}"
  stop_runners
  load_config
  MANAGER_STARTED_EPOCH="$(date +%s)"
  start_all_runners
  write_status || true
  activity "runner" "Runner manager reload completed"
}

shutdown_all() {
  stop_runners
  if [[ -n "${STATUS_PID}" ]]; then
    kill "${STATUS_PID}" 2>/dev/null || true
    wait "${STATUS_PID}" 2>/dev/null || true
  fi
}
trap shutdown_all TERM INT EXIT

prepare_paths
load_config
rm -f "${RELOAD_FILE}"
wait_for_docker
install_compose
status_loop &
STATUS_PID=$!

start_all_runners

while true; do
  if [[ -f "${RELOAD_FILE}" ]]; then
    rm -f "${RELOAD_FILE}"
    reload_runners "Dashboard requested runner reload"
    sleep 2
    continue
  fi

  runner_exited=false
  if (( ${#RUNNER_PIDS[@]} > 0 )); then
    for pid in "${RUNNER_PIDS[@]}"; do
      if [[ -z "${pid}" ]] || ! kill -0 "${pid}" 2>/dev/null; then
        runner_exited=true
        break
      fi
    done
  fi

  if [[ "${runner_exited}" == true ]]; then
    log "A runner process exited; recovering configured runners in-process"
    activity "runner" "Runner process exited; automatic recovery started"
    sleep 3
    reload_runners "Recovering configured runners"
    sleep 5
    continue
  fi

  sleep 2
done
