#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${FORGECORE_APP_ROOT:-/data}"
STORAGE_ROOT="${FORGECORE_STORAGE_ROOT:-/storage}"
STATE_DIR="${APP_ROOT}/state"
REQUEST_DIR="${STATE_DIR}/agent-requests"
RESET_DIR="${STATE_DIR}/agent-resets"
AGENT_ROOT="${STORAGE_ROOT}/agents"
LOG_DIR="${STORAGE_ROOT}/logs"
DIST_ROOT="${FORGECORE_RUNNER_DIST_ROOT:-/home/runner}"

mkdir -p "${REQUEST_DIR}" "${RESET_DIR}" "${AGENT_ROOT}" "${LOG_DIR}"

log(){
  printf '%s [runner-manager] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "${LOG_DIR}/agent-manager.log"
}

slugify(){
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's#[^a-z0-9]+#-#g;s#^-+##;s#-+$##'
}

state_file(){ printf '%s/agent-%s.json' "${STATE_DIR}" "$1"; }
pid_file(){ printf '%s/agent-%s.pid' "${STATE_DIR}" "$1"; }

write_state(){
  local id="$1" repo="$2" phase="$3" message="$4" online="${5:-false}" pid="${6:-null}"
  jq -n     --arg repository "${repo}"     --arg phase "${phase}"     --arg message "${message}"     --argjson online "${online}"     --argjson pid "${pid}"     --argjson updatedEpoch "$(date +%s)"     '{repository:$repository,phase:$phase,message:$message,online:$online,pid:$pid,updatedEpoch:$updatedEpoch}'     > "$(state_file "${id}").tmp"
  mv "$(state_file "${id}").tmp" "$(state_file "${id}")"
}

copy_distribution(){
  local destination="$1" item
  mkdir -p "${destination}"
  for item in "${DIST_ROOT}"/* "${DIST_ROOT}"/.[!.]* "${DIST_ROOT}"/..?*; do
    [[ -e "${item}" ]] || continue
    cp -a "${item}" "${destination}/"
  done
}

stop_agent(){
  local id="$1" pf pid
  pf="$(pid_file "${id}")"
  if [[ -f "${pf}" ]]; then
    pid="$(cat "${pf}" 2>/dev/null || true)"
    if [[ "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
      for _ in $(seq 1 20); do
        kill -0 "${pid}" 2>/dev/null || break
        sleep .25
      done
      kill -9 "${pid}" 2>/dev/null || true
    fi
  fi
  rm -f "${pf}"
}

running(){
  local id="$1" pf pid
  pf="$(pid_file "${id}")"
  [[ -f "${pf}" ]] || return 1
  pid="$(cat "${pf}" 2>/dev/null || true)"
  [[ "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" 2>/dev/null
}

start_agent(){
  local repo="$1" id dir log_file pid start_size
  id="$(slugify "${repo}")"
  dir="${AGENT_ROOT}/${id}"
  log_file="${LOG_DIR}/agent-${id}.log"
  [[ -f "${dir}/.forgecore-agent.json" && -x "${dir}/run.sh" ]] || return 0
  running "${id}" && return 0

  start_size=0
  [[ -f "${log_file}" ]] && start_size="$(stat -c %s "${log_file}" 2>/dev/null || echo 0)"
  write_state "${id}" "${repo}" "starting" "Starting GitHub Actions listener" false null

  (
    cd "${dir}"
    export DOCKER_HOST="${DOCKER_HOST:-tcp://docker:2375}"
    exec ./run.sh
  ) >> "${log_file}" 2>&1 &
  pid="$!"
  printf '%s\n' "${pid}" > "$(pid_file "${id}")"

  for _ in $(seq 1 50); do
    if ! kill -0 "${pid}" 2>/dev/null; then
      write_state "${id}" "${repo}" "error" "Runner exited before becoming ready" false null
      return 0
    fi
    if tail -c "+$((start_size + 1))" "${log_file}" 2>/dev/null | grep -Fq "Listening for Jobs"; then
      write_state "${id}" "${repo}" "online" "Listening for GitHub Actions jobs" true "${pid}"
      return 0
    fi
    sleep .4
  done

  write_state "${id}" "${repo}" "connecting" "Process is running; waiting for GitHub listener readiness" false "${pid}"
}

configure_request(){
  local request="$1" repo token replace requested_name id dir name reg_log rc
  repo="$(jq -r '.repository // empty' "${request}")"
  token="$(jq -r '.registrationToken // empty' "${request}")"
  replace="$(jq -r '.replaceExisting // false' "${request}")"
  requested_name="$(jq -r '.runnerName // empty' "${request}")"
  [[ "${repo}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ && -n "${token}" ]] || { rm -f "${request}"; return 0; }

  id="$(slugify "${repo}")"
  dir="${AGENT_ROOT}/${id}"
  name="ForgeCore-${id}"
  if [[ -n "${requested_name}" && "${requested_name}" =~ ^[A-Za-z0-9][A-Za-z0-9._\ -]{0,63}$ ]]; then
    name="${requested_name}"
  fi
  reg_log="${LOG_DIR}/agent-registration-${id}.log"
  stop_agent "${id}"

  if [[ "${replace}" == "true" ]]; then
    rm -rf "${dir}"
  elif [[ -f "${dir}/.forgecore-agent.json" ]]; then
    rm -f "${request}"
    start_agent "${repo}"
    return 0
  fi

  rm -rf "${dir}"
  mkdir -p "${dir}"
  copy_distribution "${dir}"
  write_state "${id}" "${repo}" "registering" "Registering local ForgeCore Runner with GitHub" false null

  set +e
  (
    cd "${dir}"
    ./config.sh       --unattended       --url "https://github.com/${repo}"       --token "${token}"       --name "${name}"       --labels "ForgeCore"       --disableupdate       --work "_work"
  ) > "${reg_log}" 2>&1
  rc="$?"
  set -e

  if [[ "${rc}" -ne 0 || ! -f "${dir}/.runner" ]]; then
    write_state "${id}" "${repo}" "error" "GitHub registration failed. Open Runner details for diagnostics." false null
    log "registration failed for ${repo}"
    return 0
  fi

  jq -n     --arg kind "ForgeCoreAgent"     --arg repository "${repo}"     --arg name "${name}"     --argjson createdEpoch "$(date +%s)"     '{kind:$kind,repository:$repository,name:$name,createdEpoch:$createdEpoch}'     > "${dir}/.forgecore-agent.json"
  chmod 600 "${dir}/.forgecore-agent.json" "${dir}/.runner" "${dir}/.credentials" 2>/dev/null || true
  rm -f "${request}"
  log "registered local Runner ${name} for ${repo}"
  start_agent "${repo}"
}

reset_request(){
  local request="$1" repo token id dir
  repo="$(jq -r '.repository // empty' "${request}")"
  token="$(jq -r '.removeToken // empty' "${request}")"
  id="$(basename "${request}" .json)"
  dir="${AGENT_ROOT}/${id}"
  stop_agent "${id}"
  if [[ -d "${dir}" && -f "${dir}/.runner" && -n "${token}" ]]; then
    set +e
    (cd "${dir}" && ./config.sh remove --unattended --token "${token}") >> "${LOG_DIR}/agent-registration-${id}.log" 2>&1
    set -e
  fi
  rm -rf "${dir}"
  rm -f "$(state_file "${id}")" "${request}"
  log "removed local Runner for ${repo:-${id}}"
}

process_requests(){
  local file
  shopt -s nullglob
  for file in "${RESET_DIR}"/*.json; do reset_request "${file}"; done
  for file in "${REQUEST_DIR}"/*.json; do configure_request "${file}"; done
  shopt -u nullglob
}

start_saved(){
  local meta repo
  shopt -s nullglob
  for meta in "${AGENT_ROOT}"/*/.forgecore-agent.json; do
    repo="$(jq -r '.repository // empty' "${meta}" 2>/dev/null || true)"
    [[ "${repo}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] && start_agent "${repo}"
  done
  shopt -u nullglob
}

cleanup(){
  local pf pid
  shopt -s nullglob
  for pf in "${STATE_DIR}"/agent-*.pid; do
    pid="$(cat "${pf}" 2>/dev/null || true)"
    [[ "${pid}" =~ ^[0-9]+$ ]] && kill "${pid}" 2>/dev/null || true
  done
  shopt -u nullglob
}
trap cleanup EXIT INT TERM

log "ForgeCore Clean Runner Manager started"
while true; do
  process_requests
  start_saved
  sleep 3
done
