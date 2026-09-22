#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${FORGECORE_APP_ROOT:-/forgecore/app}"
STORAGE_ROOT="${FORGECORE_STORAGE_ROOT:-/forgecore/storage}"
CONFIG_DIR="${APP_ROOT}/config"
RUNNER_CONFIG_DIR="${CONFIG_DIR}/runners"
STATE_DIR="${APP_ROOT}/state"
WWW_DIR="${STATE_DIR}/www"
STATIC_WWW="${FORGECORE_STATIC_WWW:-/forgecore/static-www}"
CONFIG_FILE="${CONFIG_DIR}/forgecore.env"
DEFAULT_CONFIG="${FORGECORE_DEFAULT_CONFIG:-/forgecore/defaults/forgecore.env.example}"
DEFAULT_RUNNER_CONFIG="${FORGECORE_DEFAULT_RUNNER_CONFIG:-/forgecore/defaults/runner.env.example}"

declare -a RUNNER_PIDS=()
STATUS_PID=""

log() {
  printf '[forgecore] %s\n' "$*"
}

prepare_paths() {
  sudo mkdir -p "${CONFIG_DIR}" "${RUNNER_CONFIG_DIR}" "${STATE_DIR}" "${WWW_DIR}"
  sudo mkdir -p "${STORAGE_ROOT}/docker"
  sudo mkdir -p     "${STORAGE_ROOT}/runners"     "${STORAGE_ROOT}/workspaces"     "${STORAGE_ROOT}/cache/docker-config/cli-plugins"     "${STORAGE_ROOT}/cache/go-build"     "${STORAGE_ROOT}/cache/go-mod"     "${STORAGE_ROOT}/cache/npm"     "${STORAGE_ROOT}/cache/playwright"     "${STORAGE_ROOT}/cache/toolcache"     "${STORAGE_ROOT}/artifacts"     "${STORAGE_ROOT}/logs"

  sudo chown -R runner:docker "${APP_ROOT}"
  sudo chown -R runner:docker     "${STORAGE_ROOT}/runners"     "${STORAGE_ROOT}/workspaces"     "${STORAGE_ROOT}/cache"     "${STORAGE_ROOT}/artifacts"     "${STORAGE_ROOT}/logs"

  if [[ ! -f "${CONFIG_FILE}" ]]; then
    cp "${DEFAULT_CONFIG}" "${CONFIG_FILE}"
    chmod 600 "${CONFIG_FILE}"
  fi

  if [[ ! -f "${RUNNER_CONFIG_DIR}/runner.env.example" ]]; then
    cp "${DEFAULT_RUNNER_CONFIG}" "${RUNNER_CONFIG_DIR}/runner.env.example"
    chmod 600 "${RUNNER_CONFIG_DIR}/runner.env.example"
  fi

  cp -f "${STATIC_WWW}/index.html" "${WWW_DIR}/index.html"
}

load_config() {
  # shellcheck disable=SC1090
  source "${CONFIG_FILE}"

  : "${RUNNER_NAME_PREFIX:=beelink}"
  : "${RUNNER_LABELS:=beelink,forgecore}"
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
    x86_64|amd64)
      compose_arch="x86_64"
      compose_sha="${COMPOSE_SHA256_X86_64}"
      ;;
    aarch64|arm64)
      compose_arch="aarch64"
      compose_sha="${COMPOSE_SHA256_AARCH64}"
      ;;
    *)
      log "unsupported architecture for Docker Compose: ${machine}"
      return 1
      ;;
  esac

  mkdir -p "${plugin_dir}"

  if [[ -x "${plugin}" ]] && "${plugin}" version >/dev/null 2>&1; then
    return 0
  fi

  log "installing Docker Compose v${COMPOSE_VERSION} for ${compose_arch}"
  curl -fsSL --retry 3     "https://github.com/docker/compose/releases/download/v${COMPOSE_VERSION}/docker-compose-linux-${compose_arch}"     -o "${plugin}.tmp"

  printf '%s  %s\n' "${compose_sha}" "${plugin}.tmp" | sha256sum -c -
  mv "${plugin}.tmp" "${plugin}"
  chmod +x "${plugin}"
}

slugify() {
  printf '%s' "$1"     | tr '[:upper:]' '[:lower:]'     | sed -E 's#[^a-z0-9]+#-#g; s#^-+##; s#-+$##'
}

copy_runner_distribution() {
  local destination="$1"
  local item

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

start_runner_from_config() {
  local config_file="$1"
  local REPOSITORY=""
  local REGISTRATION_TOKEN=""
  local NAME=""
  local LABELS=""
  local repo slug runner_dir work_dir runner_name labels pid

  # shellcheck disable=SC1090
  source "${config_file}"

  repo="${REPOSITORY}"
  labels="${LABELS:-${RUNNER_LABELS}}"

  if [[ -z "${repo}" ]]; then
    log "skipping ${config_file}: REPOSITORY is empty"
    return 0
  fi

  if [[ ! "${repo}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
    log "invalid repository in ${config_file}: ${repo}"
    return 1
  fi

  slug="$(slugify "${repo}")"
  runner_dir="${STORAGE_ROOT}/runners/${slug}"
  work_dir="${STORAGE_ROOT}/workspaces/${slug}"
  runner_name="${NAME:-${RUNNER_NAME_PREFIX}-${slug}}"
  runner_name="${runner_name:0:63}"

  mkdir -p "${runner_dir}" "${work_dir}"

  if [[ ! -x "${runner_dir}/run.sh" ]]; then
    log "initializing runner files for ${repo}"
    copy_runner_distribution "${runner_dir}"
    rm -rf "${runner_dir}/_work"
    ln -s "${work_dir}" "${runner_dir}/_work"
  fi

  if [[ ! -f "${runner_dir}/.runner" ]]; then
    if [[ -z "${REGISTRATION_TOKEN}" ]]; then
      log "${repo} is waiting for a GitHub registration token in ${config_file}"
      return 0
    fi

    log "registering runner for ${repo}"
    (
      cd "${runner_dir}"
      ./config.sh         --unattended         --replace         --url "https://github.com/${repo}"         --token "${REGISTRATION_TOKEN}"         --name "${runner_name}"         --work "_work"         --labels "${labels}"
    )

    clear_registration_token "${config_file}"
  elif [[ -n "${REGISTRATION_TOKEN}" ]]; then
    clear_registration_token "${config_file}"
  fi

  log "starting ${runner_name}"
  (
    cd "${runner_dir}"
    ./run.sh
  ) &

  pid=$!
  printf '%s\n' "${pid}" > "${STATE_DIR}/runner-${slug}.pid"
  printf '%s\n' "${runner_name}" > "${STATE_DIR}/runner-${slug}.name"
  RUNNER_PIDS+=("${pid}")
}

write_status() {
  local docker_online=false
  local configured=0
  local online=0
  local disk_total="—"
  local disk_used="—"
  local disk_pct=0
  local runner_summary="Runner not configured"
  local pid_file pid

  if docker info >/dev/null 2>&1; then
    docker_online=true
  fi

  shopt -s nullglob
  local name_files=("${STATE_DIR}"/runner-*.name)
  configured="${#name_files[@]}"

  for pid_file in "${STATE_DIR}"/runner-*.pid; do
    [[ -f "${pid_file}" ]] || continue
    pid="$(cat "${pid_file}" 2>/dev/null || true)"

    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      online=$((online + 1))
    fi
  done
  shopt -u nullglob

  if (( configured > 0 )); then
    runner_summary="${online}/${configured} runner(s) online"
  fi

  if df -Pk "${STORAGE_ROOT}" >/dev/null 2>&1; then
    disk_pct="$(df -Pk "${STORAGE_ROOT}" | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
    disk_total="$(df -hP "${STORAGE_ROOT}" | awk 'NR==2 {print $2}')"
    disk_used="$(df -hP "${STORAGE_ROOT}" | awk 'NR==2 {print $3}')"
  fi

  jq -n     --argjson runner_online "$([[ "${online}" -gt 0 ]] && echo true || echo false)"     --arg runner_name "${runner_summary}"     --argjson docker_online "${docker_online}"     --arg disk_used "${disk_used}"     --arg disk_total "${disk_total}"     --argjson disk_used_percent "${disk_pct:-0}"     --arg disk_path "${STORAGE_ROOT}"     --argjson cleanup_interval_days "$((CLEANUP_INTERVAL_HOURS / 24))"     --argjson cache_max_age_days "${CACHE_MAX_AGE_DAYS}"     '{
      runner_online: $runner_online,
      runner_name: $runner_name,
      docker_online: $docker_online,
      disk_used: $disk_used,
      disk_total: $disk_total,
      disk_used_percent: $disk_used_percent,
      disk_path: $disk_path,
      cleanup_interval_days: $cleanup_interval_days,
      cache_max_age_days: $cache_max_age_days
    }' > "${WWW_DIR}/status.json.tmp"

  mv "${WWW_DIR}/status.json.tmp" "${WWW_DIR}/status.json"
}

status_loop() {
  while true; do
    write_status || true
    sleep 10
  done
}

stop_all() {
  local pid

  log "stopping runners"
  for pid in "${RUNNER_PIDS[@]:-}"; do
    kill "${pid}" 2>/dev/null || true
  done

  if [[ -n "${STATUS_PID}" ]]; then
    kill "${STATUS_PID}" 2>/dev/null || true
  fi
}
trap stop_all TERM INT EXIT

prepare_paths
load_config
rm -f "${STATE_DIR}"/runner-*.pid "${STATE_DIR}"/runner-*.name

wait_for_docker
install_compose

status_loop &
STATUS_PID=$!

shopt -s nullglob
runner_configs=("${RUNNER_CONFIG_DIR}"/*.env)
shopt -u nullglob

for config_file in "${runner_configs[@]}"; do
  start_runner_from_config "${config_file}"
done

if (( ${#RUNNER_PIDS[@]} == 0 )); then
  log "ForgeCore is running, but no configured GitHub runner is ready"
  log "copy ${RUNNER_CONFIG_DIR}/runner.env.example to a .env file and add a fresh registration token"
  wait "${STATUS_PID}"
  exit 0
fi

wait -n "${RUNNER_PIDS[@]}"
log "a runner process exited; restarting ForgeCore runner manager"
exit 1
