#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${FORGECORE_APP_ROOT:-/forgecore/app}"
STORAGE_ROOT="${FORGECORE_STORAGE_ROOT:-/forgecore/storage}"
CONFIG_DIR="${APP_ROOT}/config"
APP_CONFIG_DIR="${CONFIG_DIR}/apps"
PUBLISH_PRESET_DIR="${CONFIG_DIR}/publish-presets"
GLOBAL_CONFIG="${CONFIG_DIR}/global.json"
V1_RUNNER_CONFIG_DIR="${CONFIG_DIR}/runners"
STATE_DIR="${APP_ROOT}/state"
RUNNER_REQUEST_DIR="${STATE_DIR}/runner-requests"
RELOAD_FILE="${STATE_DIR}/reload-runners.request"
LOG_FILE="${STORAGE_ROOT}/logs/runner-manager.log"
ACTIVITY_FILE="${STATE_DIR}/activity.log"
RUNTIME_VERSION="${FORGECORE_RUNTIME_VERSION:-dev}"
FORGECORE_MANAGER_BUILD="0.1.0-beta.47"
RUNNER_DIST_ROOT="${FORGECORE_RUNNER_DIST_ROOT:-/home/runner}"
RUNNER_STARTUP_GRACE_SECONDS="${FORGECORE_RUNNER_STARTUP_GRACE_SECONDS:-2}"
RUNNER_ACQUIRE_STALL_SECONDS="${FORGECORE_RUNNER_ACQUIRE_STALL_SECONDS:-90}"
RUNNER_IDLE_RECYCLE_SECONDS="${FORGECORE_RUNNER_IDLE_RECYCLE_SECONDS:-300}"
RUNNER_ENGINE_ROOT="${STORAGE_ROOT}/runners"
V1_RUNNER_ENGINE_ROOT="${STORAGE_ROOT}/runners/v2"
V1_RUNNER_MIGRATION_MARKER="${STATE_DIR}/v1-runner-config.migrated.json"
RUNNER_METADATA_NAME=".forgecore-runner.json"
RUNNER_BACKUP_ROOT="${STORAGE_ROOT}/runner-backups"
DEPENDENCY_READY_FILE="${STATE_DIR}/dependencies.ready"
DEPENDENCY_ERROR_FILE="${STATE_DIR}/dependencies.error"
COMPOSE_VERSION="5.5.1"
COMPOSE_SHA256_X86_64="db1889184726840f75c4f9c001048430d4f25b3be3cb084d3ddd762bc0aed576"
COMPOSE_SHA256_AARCH64="732e3a84c1a0f67256ce80bc2598a24546b10ca05f9faa97efceb1171ece2ef7"
CLEANUP_INTERVAL_HOURS=168
CACHE_MAX_AGE_DAYS=14
WORKSPACE_MAX_AGE_DAYS=30
DISK_CLEANUP_THRESHOLD_PERCENT=85
BUILDKIT_KEEP_STORAGE_GB=50

declare -a RUNNER_PIDS=()
STATUS_PID=""
DEPENDENCY_PID=""
MANAGER_STARTED_EPOCH="$(date +%s)"

log() {
  printf '[forgecore] %s\n' "$*"
  if [[ -d "${STORAGE_ROOT}/logs" ]]; then
    printf '%s [forgecore] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "${LOG_FILE}" || true
  fi
}

write_service_error() {
  mkdir -p "${STATE_DIR}" 2>/dev/null || true
  printf '%s\n' "$*" > "${STATE_DIR}/runner-service.error" 2>/dev/null || true
}

manager_error_trap() {
  local rc="$1" line="$2" command="$3"
  trap - ERR
  write_service_error "Runner manager failed before becoming healthy (exit ${rc}, line ${line}): ${command}"
  printf '[forgecore] FATAL exit=%s line=%s command=%s\n' "${rc}" "${line}" "${command}" >&2
  exit "${rc}"
}

trap 'manager_error_trap "$?" "$LINENO" "$BASH_COMMAND"' ERR

activity() {
  local kind="$1" message="$2"
  jq -cn --argjson epoch "$(date +%s)" --arg type "${kind}" --arg message "${message}"     '{epoch:$epoch,type:$type,message:$message}' >> "${ACTIVITY_FILE}" || true
}

prepare_paths() {
  sudo mkdir -p "${CONFIG_DIR}" "${APP_CONFIG_DIR}" "${PUBLISH_PRESET_DIR}" "${STATE_DIR}" "${RUNNER_REQUEST_DIR}"
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

  local writable_dir
  for writable_dir in \
    "${STORAGE_ROOT}/runners" \
    "${STORAGE_ROOT}/workspaces" \
    "${STORAGE_ROOT}/cache" \
    "${STORAGE_ROOT}/artifacts" \
    "${STORAGE_ROOT}/logs"; do
    if [[ ! -w "${writable_dir}" ]]; then
      sudo chown -R runner:docker "${writable_dir}" 2>/dev/null || true
    fi
  done

  if [[ ! -w "${STORAGE_ROOT}/runners" ]]; then
    write_service_error "ForgeCore cannot write to the existing external runners directory: ${STORAGE_ROOT}/runners"
    return 1
  fi

  mkdir -p "${RUNNER_ENGINE_ROOT}" "${RUNNER_REQUEST_DIR}"
  if [[ ! -w "${RUNNER_ENGINE_ROOT}" ]]; then
    write_service_error "ForgeCore cannot write to the runner engine directory: ${RUNNER_ENGINE_ROOT}"
    return 1
  fi

  migrate_v1_runner_state
}

normalize_app_permissions() {
  # The dashboard runs in a separate root-based Python container. Any config
  # file it atomically replaces can otherwise become root:root mode 0600,
  # which the actions-runner user cannot read.
  sudo chown -R runner:docker "${CONFIG_DIR}" "${STATE_DIR}"
}

write_runner_metadata() {
  local runner_dir="$1" repo="$2"
  local metadata="${runner_dir}/${RUNNER_METADATA_NAME}"
  mkdir -p "${runner_dir}"
  jq -n \
    --arg repository "${repo}" \
    --argjson updatedEpoch "$(date +%s)" \
    '{schemaVersion:1,kind:"ForgeCoreRunner",repository:$repository,updatedEpoch:$updatedEpoch}' \
    > "${metadata}.tmp"
  chmod 600 "${metadata}.tmp"
  mv "${metadata}.tmp" "${metadata}"
}

migrate_v1_runner_state() {
  local config_file repo slug source_dir target_dir backup_dir stamp source_mode
  [[ -f "${V1_RUNNER_MIGRATION_MARKER}" ]] && return 0

  mkdir -p "${RUNNER_BACKUP_ROOT}"
  log "checking one-time v1 runner migration"

  if [[ -d "${V1_RUNNER_CONFIG_DIR}" ]]; then
    shopt -s nullglob
    local configs=("${V1_RUNNER_CONFIG_DIR}"/*.env)
    shopt -u nullglob

    for config_file in "${configs[@]}"; do
      [[ "$(basename "${config_file}")" == "runner.env.example" ]] && continue
      repo="$(sed -n -E 's/^[[:space:]]*REPOSITORY="([^"]+)"[[:space:]]*$/\1/p' "${config_file}" | head -n 1)"
      [[ "${repo}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || { rm -f "${config_file}"; continue; }
      slug="$(slugify "${repo}")"
      source_dir="${V1_RUNNER_ENGINE_ROOT}/${slug}"
      target_dir="${RUNNER_ENGINE_ROOT}/${slug}"

      if [[ -d "${source_dir}" ]]; then
        source_mode="$(runner_identity_mode "${source_dir}")"
        if [[ "${source_mode}" == "persistent" ]]; then
          if [[ -e "${target_dir}" ]]; then
            stamp="$(date -u +%Y%m%dT%H%M%SZ)"
            backup_dir="${RUNNER_BACKUP_ROOT}/${slug}-pre-v2-${stamp}"
            mv "${target_dir}" "${backup_dir}"
            log "archived previous runner directory for ${repo}: ${backup_dir}"
          fi
          mv "${source_dir}" "${target_dir}"
          log "migrated persistent runner identity for ${repo}"
        elif [[ ! -e "${target_dir}" ]]; then
          mv "${source_dir}" "${target_dir}"
        fi
      fi

      mkdir -p "${target_dir}"
      write_runner_metadata "${target_dir}" "${repo}"
      rm -f "${config_file}"
      activity "runner" "v1 runner configuration migrated to v2 metadata for ${repo}"
    done

    rm -f "${V1_RUNNER_CONFIG_DIR}/runner.env.example"
    rmdir "${V1_RUNNER_CONFIG_DIR}" 2>/dev/null || true
  fi

  rmdir "${V1_RUNNER_ENGINE_ROOT}" 2>/dev/null || true
  rm -f "${STATE_DIR}/runner-engine-v2.initialized" "${STATE_DIR}/runner-layout-standard.initialized"
  jq -n \
    --argjson migratedEpoch "$(date +%s)" \
    '{schemaVersion:1,kind:"ForgeCoreV1RunnerMigration",migratedEpoch:$migratedEpoch}' \
    > "${V1_RUNNER_MIGRATION_MARKER}.tmp"
  chmod 600 "${V1_RUNNER_MIGRATION_MARKER}.tmp"
  mv "${V1_RUNNER_MIGRATION_MARKER}.tmp" "${V1_RUNNER_MIGRATION_MARKER}"
}

load_config() {
  CLEANUP_INTERVAL_HOURS=168
  CACHE_MAX_AGE_DAYS=14
  WORKSPACE_MAX_AGE_DAYS=30
  DISK_CLEANUP_THRESHOLD_PERCENT=85
  BUILDKIT_KEEP_STORAGE_GB=50
  if [[ -f "${GLOBAL_CONFIG}" ]]; then
    CLEANUP_INTERVAL_HOURS="$(jq -r '.cleanup.intervalHours // 168' "${GLOBAL_CONFIG}" 2>/dev/null || echo 168)"
    CACHE_MAX_AGE_DAYS="$(jq -r '.cleanup.cacheMaxAgeDays // 14' "${GLOBAL_CONFIG}" 2>/dev/null || echo 14)"
    WORKSPACE_MAX_AGE_DAYS="$(jq -r '.cleanup.workspaceMaxAgeDays // 30' "${GLOBAL_CONFIG}" 2>/dev/null || echo 30)"
    DISK_CLEANUP_THRESHOLD_PERCENT="$(jq -r '.cleanup.diskThresholdPercent // 85' "${GLOBAL_CONFIG}" 2>/dev/null || echo 85)"
    BUILDKIT_KEEP_STORAGE_GB="$(jq -r '.cleanup.buildkitKeepStorageGB // 50' "${GLOBAL_CONFIG}" 2>/dev/null || echo 50)"
  fi
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

dependency_loop() {
  local announced_ready=false
  rm -f "${DEPENDENCY_READY_FILE}"
  while true; do
    if docker info >/dev/null 2>&1; then
      if install_compose >/dev/null 2>&1; then
        : > "${DEPENDENCY_READY_FILE}"
        rm -f "${DEPENDENCY_ERROR_FILE}"
        if [[ "${announced_ready}" != true ]]; then
          log "Docker/Compose dependencies are ready"
          activity "runner" "Docker/Compose dependencies are ready"
          announced_ready=true
        fi
        sleep 15
        continue
      fi
      printf '%s\n' "Docker is reachable, but Docker Compose is not ready yet. ForgeCore will keep retrying in the background." > "${DEPENDENCY_ERROR_FILE}"
    else
      printf '%s\n' "Isolated Docker engine is not ready yet. ForgeCore runner manager remains online and will keep retrying in the background." > "${DEPENDENCY_ERROR_FILE}"
    fi
    rm -f "${DEPENDENCY_READY_FILE}"
    announced_ready=false
    sleep 5
  done
}

slugify() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's#[^a-z0-9]+#-#g; s#^-+##; s#-+$##'
}

copy_runner_distribution() {
  local destination="$1" item
  for item in "${RUNNER_DIST_ROOT}"/* "${RUNNER_DIST_ROOT}"/.[!.]* "${RUNNER_DIST_ROOT}"/..?*; do
    [[ -e "${item}" ]] || continue
    [[ "$(basename "${item}")" == ".docker" ]] && continue
    cp -a "${item}" "${destination}/"
  done
}

reset_runner_install() {
  local runner_dir="$1"
  rm -rf "${runner_dir}"
  mkdir -p "${runner_dir}"
  copy_runner_distribution "${runner_dir}"
}

clear_registration_request() {
  local file="${1:-}"
  [[ -n "${file}" && -f "${file}" ]] && rm -f "${file}"
}

runner_identity_mode() {
  local runner_dir="$1"
  local settings="${runner_dir}/.runner"
  if [[ ! -f "${settings}" ]]; then
    printf '%s\n' "unregistered"
    return 0
  fi
  if ! jq -e 'type == "object"' "${settings}" >/dev/null 2>&1; then
    printf '%s\n' "invalid"
    return 0
  fi
  if jq -e '(.Ephemeral // .ephemeral // false) == true' "${settings}" >/dev/null 2>&1; then
    printf '%s\n' "ephemeral"
  else
    printf '%s\n' "persistent"
  fi
}

clear_runner_identity() {
  local runner_dir="$1"
  rm -f \
    "${runner_dir}/.runner" \
    "${runner_dir}/.credentials" \
    "${runner_dir}/.credentials_rsaparams" \
    "${runner_dir}/.credentials_migrated" \
    "${runner_dir}/.service"
}

write_runner_runtime_state() {
  local slug="$1" repo="$2" phase="$3" mode="$4" message="$5"
  local path="${STATE_DIR}/runner-${slug}.runtime.json"
  jq -n \
    --argjson epoch "$(date +%s)" \
    --arg repository "${repo}" \
    --arg phase "${phase}" \
    --arg mode "${mode}" \
    --arg message "${message}" \
    '{epoch:$epoch,repository:$repository,phase:$phase,mode:$mode,message:$message}' \
    > "${path}.tmp"
  mv "${path}.tmp" "${path}"
}

runner_log_ready_since() {
  local runner_log="$1" offset="$2"
  [[ -f "${runner_log}" ]] || return 1
  tail -c "+$((offset + 1))" "${runner_log}" 2>/dev/null | grep -Fq "Listening for Jobs"
}

runner_worker_active() {
  local proc cmdline
  for proc in /proc/[0-9]*/cmdline; do
    [[ -r "${proc}" ]] || continue
    cmdline="$(tr '\0' ' ' < "${proc}" 2>/dev/null || true)"
    [[ "${cmdline}" == *"/bin/Runner.Worker"* ]] && return 0
  done
  return 1
}
runner_diag_watchdog_reason() {
  local slug="$1" runner_dir="$2" listener_start="$3"
  local diag mtime segment seen_file seen now age
  diag="$(ls -1t "${runner_dir}"/_diag/Runner_*.log 2>/dev/null | head -n 1 || true)"
  [[ -n "${diag}" ]] || return 1
  mtime="$(stat -c %Y "${diag}" 2>/dev/null || echo 0)"
  (( mtime >= listener_start )) || return 1
  segment="$(tail -n 500 "${diag}" 2>/dev/null || true)"
  if grep -Eq 'RunnerSessionInvalid|session (is )?invalid|session has been deleted|session conflict' <<< "${segment}"; then
    printf '%s\n' "session-invalid"
    return 0
  fi
  seen_file="${STATE_DIR}/runner-${slug}.acquire-seen-epoch"
  if grep -Fq 'Acknowledging runner request' <<< "${segment}"; then
    now="$(date +%s)"
    if [[ ! -f "${seen_file}" ]]; then
      printf '%s\n' "${now}" > "${seen_file}"
      return 1
    fi
    seen="$(cat "${seen_file}" 2>/dev/null || echo "${now}")"
    [[ "${seen}" =~ ^[0-9]+$ ]] || seen="${now}"
    age=$((now - seen))
    if (( age >= RUNNER_ACQUIRE_STALL_SECONDS )); then
      printf '%s\n' "acquire-stall"
      return 0
    fi
  else
    rm -f "${seen_file}"
  fi
  return 1
}

prepare_runner_hooks() {
  local slug="$1" hook_dir start_hook complete_hook
  hook_dir="${APP_ROOT}/hooks"
  mkdir -p "${hook_dir}"
  start_hook="${hook_dir}/job-started-${slug}.sh"
  complete_hook="${hook_dir}/job-completed-${slug}.sh"

  cat > "${start_hook}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
: "${FORGECORE_HOOK_STATE_DIR:?}"
: "${FORGECORE_HOOK_SLUG:?}"
: "${FORGECORE_RUNTIME_VERSION:?}"
printf '%s\n' "$(date +%s)" > "${FORGECORE_HOOK_STATE_DIR}/runner-${FORGECORE_HOOK_SLUG}.job-started-epoch"
workflow="${GITHUB_WORKFLOW:-}"
event="${GITHUB_EVENT_NAME:-}"
ref_name="${GITHUB_REF_NAME:-}"
runtime="${FORGECORE_RUNTIME_VERSION}"

if [[ "${workflow}" != "ForgeCore runner live check" ]]; then
  for _ in $(seq 1 60); do
    [[ -f "${FORGECORE_HOOK_DEPENDENCY_READY_FILE:-}" ]] && break
    sleep 2
  done
  if [[ ! -f "${FORGECORE_HOOK_DEPENDENCY_READY_FILE:-}" ]]; then
    if [[ -n "${FORGECORE_HOOK_DEPENDENCY_ERROR_FILE:-}" && -f "${FORGECORE_HOOK_DEPENDENCY_ERROR_FILE}" ]]; then
      cat "${FORGECORE_HOOK_DEPENDENCY_ERROR_FILE}" >&2
    else
      echo "ForgeCore Docker/Compose dependencies are not ready." >&2
    fi
    exit 43
  fi
fi
current_beta=""
if [[ "${runtime}" =~ beta\.([0-9]+)$ ]]; then current_beta="${BASH_REMATCH[1]}"; fi
stale_beta() {
  local value="$1" n=""
  if [[ "${value}" =~ beta\.([0-9]+)$ ]]; then
    n="${BASH_REMATCH[1]}"
    [[ -n "${current_beta}" ]] && (( n < current_beta ))
    return
  fi
  return 1
}
if [[ "${workflow}" == "Release channel preflight" && "${event}" != "workflow_dispatch" ]]; then
  echo "ForgeCore rejected stale preflight event: ${event}" >&2
  exit 42
fi
if [[ "${workflow}" == "Release" ]] && stale_beta "${ref_name}"; then
  echo "ForgeCore rejected stale release ${ref_name}; runner runtime is ${runtime}" >&2
  exit 42
fi
if [[ "${workflow}" == "Publish prerelease request" ]] && stale_beta "${ref_name}"; then
  echo "ForgeCore rejected stale prerelease request ${ref_name}; runner runtime is ${runtime}" >&2
  exit 42
fi
EOF

  cat > "${complete_hook}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
: "${FORGECORE_HOOK_STATE_DIR:?}"
: "${FORGECORE_HOOK_SLUG:?}"
printf '%s\n' "$(date +%s)" > "${FORGECORE_HOOK_STATE_DIR}/runner-${FORGECORE_HOOK_SLUG}.job-completed-epoch"
EOF
  chmod 700 "${start_hook}" "${complete_hook}"
}
runner_log_watchdog_reason() {
  local runner_log="$1" offset="$2"
  local segment now mtime age
  [[ -f "${runner_log}" ]] || return 1
  segment="$(tail -c "+$((offset + 1))" "${runner_log}" 2>/dev/null || true)"

  if grep -Eq 'Job .+ completed with result:' <<< "${segment}"; then
    printf '%s\n' "post-job"
    return 0
  fi

  if grep -Fq 'Acknowledging runner request' <<< "${segment}"; then
    mtime="$(stat -c %Y "${runner_log}" 2>/dev/null || echo 0)"
    now="$(date +%s)"
    age=$((now - mtime))
    if (( mtime > 0 && age >= RUNNER_ACQUIRE_STALL_SECONDS )); then
      printf '%s\n' "acquire-stall"
      return 0
    fi
  fi
  return 1
}

runner_watchdog_recycle_reason() {
  local repo_file slug repo pid_file pid runner_log offset_file offset reason runner_dir start_file listener_start now
  runner_worker_active && return 1

  shopt -s nullglob
  local repo_files=("${STATE_DIR}"/runner-*.repo)
  shopt -u nullglob

  for repo_file in "${repo_files[@]}"; do
    slug="${repo_file##*/runner-}"; slug="${slug%.repo}"
    repo="$(cat "${repo_file}" 2>/dev/null || true)"
    pid_file="${STATE_DIR}/runner-${slug}.pid"
    [[ -f "${pid_file}" ]] || continue
    pid="$(cat "${pid_file}" 2>/dev/null || true)"
    [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null || continue
    runner_dir="${RUNNER_ENGINE_ROOT}/${slug}"
    runner_log="${STORAGE_ROOT}/logs/runner-${slug}.log"
    offset_file="${STATE_DIR}/runner-${slug}.log-offset"
    start_file="${STATE_DIR}/runner-${slug}.listener-start-epoch"
    offset="$(cat "${offset_file}" 2>/dev/null || echo 0)"
    listener_start="$(cat "${start_file}" 2>/dev/null || echo 0)"
    [[ "${listener_start}" =~ ^[0-9]+$ ]] || listener_start=0

    reason="$(runner_log_watchdog_reason "${runner_log}" "${offset}" || true)"
    if [[ -z "${reason}" ]]; then
      reason="$(runner_diag_watchdog_reason "${slug}" "${runner_dir}" "${listener_start}" || true)"
    fi

    case "${reason}" in
      post-job)
        printf '%s\n' "Runner watchdog recycling listener after completed job: ${repo}"
        return 0
        ;;
      acquire-stall)
        printf '%s\n' "Runner watchdog recovering stalled GitHub broker acquisition: ${repo}"
        return 0
        ;;
      session-invalid)
        printf '%s\n' "Runner watchdog recovering invalid GitHub listener session: ${repo}"
        return 0
        ;;
    esac

    now="$(date +%s)"
    if (( listener_start > 0 && now - listener_start >= RUNNER_IDLE_RECYCLE_SECONDS )); then
      printf '%s\n' "Runner watchdog refreshing idle GitHub listener session: ${repo}"
      return 0
    fi
  done
  return 1
}
prepare_real_workdir() {
  local runner_dir="$1"
  local work_dir="${runner_dir}/_work"
  if [[ -L "${work_dir}" ]]; then
    log "migrating ${work_dir} from symlink to real directory"
    rm -f "${work_dir}"
  fi
  mkdir -p "${work_dir}"
}

begin_runner_repair_backup() {
  local slug="$1" runner_dir="$2"
  local backup_dir=""
  if [[ -e "${runner_dir}" ]]; then
    mkdir -p "${RUNNER_BACKUP_ROOT}"
    backup_dir="${RUNNER_BACKUP_ROOT}/${slug}-pre-repair-$(date -u +%Y%m%dT%H%M%SZ)"
    mv "${runner_dir}" "${backup_dir}"
  fi
  printf '%s\n' "${backup_dir}"
}

restore_runner_repair_backup() {
  local runner_dir="$1" backup_dir="$2"
  [[ -n "${backup_dir}" && -d "${backup_dir}" ]] || return 0
  rm -rf "${runner_dir}"
  mv "${backup_dir}" "${runner_dir}"
}

start_runner_for_repository() {
  local repo="$1" request_file="${2:-}"
  local REGISTRATION_TOKEN="" REPAIR_EXISTING="false"
  local slug repo_label runner_dir runner_name labels pid error_file runner_log registration_log identity_mode log_offset registration_summary repair_backup=""
  local request_repo=""

  [[ -n "${repo}" ]] || return 0
  [[ "${repo}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || { log "invalid App repository: ${repo}"; return 1; }

  slug="$(slugify "${repo}")"
  if [[ -z "${request_file}" ]]; then
    request_file="${RUNNER_REQUEST_DIR}/${slug}.json"
  fi
  if [[ -f "${request_file}" ]]; then
    request_repo="$(jq -r '.repository // empty' "${request_file}" 2>/dev/null || true)"
    if [[ "${request_repo}" != "${repo}" ]]; then
      log "discarding runner request whose repository does not match its App: ${request_repo}"
      clear_registration_request "${request_file}"
    else
      REGISTRATION_TOKEN="$(jq -r '.token // empty' "${request_file}" 2>/dev/null || true)"
      [[ "$(jq -r '.repairExisting // false' "${request_file}" 2>/dev/null || echo false)" == "true" ]] && REPAIR_EXISTING="true"
    fi
  fi

  repo_label="${repo##*/}"
  labels="${repo_label}"

  runner_dir="${RUNNER_ENGINE_ROOT}/${slug}"
  runner_name="${repo_label:0:63}"
  error_file="${STATE_DIR}/runner-${slug}.error"
  runner_log="${STORAGE_ROOT}/logs/runner-${slug}.log"
  registration_log="${STORAGE_ROOT}/logs/registration-${slug}.log"

  mkdir -p "${runner_dir}"
  identity_mode="$(runner_identity_mode "${runner_dir}")"

  if [[ -n "${REGISTRATION_TOKEN}" && "${identity_mode}" != "unregistered" && "${REPAIR_EXISTING}" != "true" ]]; then
    log "blocked unconfirmed runner replacement for ${repo}; existing identity preserved"
    activity "runner" "Blocked unconfirmed runner replacement for ${repo}; existing identity preserved"
    clear_registration_request "${request_file}"
    REGISTRATION_TOKEN=""
    REPAIR_EXISTING="false"
    if [[ "${identity_mode}" == "persistent" ]]; then
      write_runner_runtime_state "${slug}" "${repo}" "checking" "persistent" "Ignored unconfirmed registration token; existing runner identity preserved"
    else
      printf '%s\n' "Runner identity needs repair, but replacement was not explicitly confirmed. Open Repair connection and confirm replacement first." > "${error_file}"
      write_runner_runtime_state "${slug}" "${repo}" "needs-repair" "${identity_mode}" "$(cat "${error_file}")"
      return 0
    fi
  fi

  if [[ -n "${REGISTRATION_TOKEN}" ]]; then
    if [[ "${REPAIR_EXISTING}" == "true" && "${identity_mode}" != "unregistered" ]]; then
      repair_backup="$(begin_runner_repair_backup "${slug}" "${runner_dir}")"
      log "explicit runner replacement authorized for ${repo}; previous identity backed up at ${repair_backup}"
    fi
    reset_runner_install "${runner_dir}"
    identity_mode="unregistered"
  elif [[ ! -x "${runner_dir}/run.sh" ]]; then
    log "initializing clean runner files for ${repo}"
    copy_runner_distribution "${runner_dir}"
  fi

  write_runner_metadata "${runner_dir}" "${repo}"
  prepare_real_workdir "${runner_dir}"
  prepare_runner_hooks "${slug}"
  rm -f "${error_file}"
  printf '%s\n' "${runner_name}" > "${STATE_DIR}/runner-${slug}.name"
  printf '%s\n' "${repo}" > "${STATE_DIR}/runner-${slug}.repo"

  identity_mode="$(runner_identity_mode "${runner_dir}")"
  write_runner_runtime_state "${slug}" "${repo}" "checking" "${identity_mode}" "Checking saved runner identity"

  if [[ "${identity_mode}" == "ephemeral" || "${identity_mode}" == "invalid" ]]; then
    log "detected ${identity_mode} runner identity for ${repo}"
    if [[ -z "${REGISTRATION_TOKEN}" ]]; then
      if [[ "${identity_mode}" == "ephemeral" ]]; then
        printf '%s\n' "Runner is one-time/ephemeral. Repair once with a fresh GitHub registration token to convert it to persistent mode." > "${error_file}"
      else
        printf '%s\n' "Runner identity could not be read safely. Repair once with a fresh GitHub registration token to rebuild it." > "${error_file}"
      fi
      write_runner_runtime_state "${slug}" "${repo}" "needs-repair" "${identity_mode}" "$(cat "${error_file}")"
      activity "runner" "Persistent migration required for ${repo}"
      return 0
    fi
  fi

  if [[ -n "${REGISTRATION_TOKEN}" && "${REPAIR_EXISTING}" == "true" ]]; then
    log "repairing persistent runner registration for ${repo}"
    write_runner_runtime_state "${slug}" "${repo}" "registering" "${identity_mode}" "Registering persistent runner"
    identity_mode="unregistered"
  fi

  if [[ "${identity_mode}" == "unregistered" ]]; then
    if [[ -z "${REGISTRATION_TOKEN}" ]]; then
      printf '%s\n' "Runner identity is missing. Open Repair and paste a fresh GitHub registration token once." > "${error_file}"
      write_runner_runtime_state "${slug}" "${repo}" "needs-repair" "unregistered" "$(cat "${error_file}")"
      return 0
    fi

    log "registering persistent runner for ${repo}"
    {
      printf '%s registration started for %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${repo}"
      printf 'Runner layout: standard registration\n'
    } > "${registration_log}"

    if ! (
      cd "${runner_dir}"
      ./config.sh \
        --unattended \
        --replace \
        --disableupdate \
        --no-default-labels \
        --url "https://github.com/${repo}" \
        --token "${REGISTRATION_TOKEN}" \
        --name "${runner_name}" \
        --work "_work" \
        --labels "${labels}"
    ) >> "${registration_log}" 2>&1; then
      registration_summary="$(tail -n 12 "${registration_log}" 2>/dev/null | tr '\n' ' ' | cut -c1-1600)"
      if [[ -n "${repair_backup}" ]]; then
        restore_runner_repair_backup "${runner_dir}" "${repair_backup}"
        identity_mode="$(runner_identity_mode "${runner_dir}")"
        clear_registration_request "${request_file}"
        REGISTRATION_TOKEN=""
        REPAIR_EXISTING="false"
        printf '%s\n' "Repair failed. Previous runner identity was restored. GitHub/config.sh: ${registration_summary}" > "${error_file}"
        write_runner_runtime_state "${slug}" "${repo}" "needs-repair" "${identity_mode}" "$(cat "${error_file}")"
        activity "runner" "Repair failed for ${repo}; previous runner identity restored"
      else
        clear_registration_request "${request_file}"
        printf '%s\n' "Registration failed. GitHub/config.sh: ${registration_summary}" > "${error_file}"
        write_runner_runtime_state "${slug}" "${repo}" "error" "unregistered" "$(cat "${error_file}")"
        activity "runner" "Clean registration failed for ${repo}; open Registration log for the GitHub error"
      fi
      return 1
    fi

    identity_mode="$(runner_identity_mode "${runner_dir}")"
    if [[ "${identity_mode}" != "persistent" ]]; then
      if [[ -n "${repair_backup}" ]]; then
        restore_runner_repair_backup "${runner_dir}" "${repair_backup}"
        identity_mode="$(runner_identity_mode "${runner_dir}")"
        clear_registration_request "${request_file}"
        REGISTRATION_TOKEN=""
        REPAIR_EXISTING="false"
        printf '%s\n' "Repair did not create a verified persistent identity. Previous runner identity was restored." > "${error_file}"
        write_runner_runtime_state "${slug}" "${repo}" "needs-repair" "${identity_mode}" "$(cat "${error_file}")"
        activity "runner" "Repair verification failed for ${repo}; previous runner identity restored"
      else
        printf '%s\n' "Registration did not create a verified persistent runner identity." > "${error_file}"
        log "refusing non-persistent runner identity for ${repo}: ${identity_mode}"
        write_runner_runtime_state "${slug}" "${repo}" "error" "${identity_mode}" "$(cat "${error_file}")"
        clear_runner_identity "${runner_dir}"
      fi
      return 1
    fi

    clear_registration_request "${request_file}"
    activity "runner" "Persistent runner registered for ${repo}"
  elif [[ -n "${REGISTRATION_TOKEN}" ]]; then
    clear_registration_request "${request_file}"
  fi

  identity_mode="$(runner_identity_mode "${runner_dir}")"
  if [[ "${identity_mode}" != "persistent" ]]; then
    printf '%s\n' "ForgeCore will only start a verified persistent runner identity." > "${error_file}"
    write_runner_runtime_state "${slug}" "${repo}" "needs-repair" "${identity_mode}" "$(cat "${error_file}")"
    return 1
  fi

  log "starting persistent runner ${runner_name}"
  if [[ -f "${runner_log}" ]]; then
    log_offset="$(wc -c < "${runner_log}")"
  else
    log_offset=0
  fi
  printf '%s runner starting: %s (%s) mode=persistent\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${runner_name}" "${repo}" >> "${runner_log}"
  write_runner_runtime_state "${slug}" "${repo}" "starting" "persistent" "Starting GitHub runner process"

  (
    cd "${runner_dir}"
    export FORGECORE_HOOK_STATE_DIR="${STATE_DIR}"
    export FORGECORE_HOOK_SLUG="${slug}"
    export FORGECORE_RUNTIME_VERSION="${RUNTIME_VERSION}"
    export FORGECORE_HOOK_DEPENDENCY_READY_FILE="${DEPENDENCY_READY_FILE}"
    export FORGECORE_HOOK_DEPENDENCY_ERROR_FILE="${DEPENDENCY_ERROR_FILE}"
    export ACTIONS_RUNNER_HOOK_JOB_STARTED="${APP_ROOT}/hooks/job-started-${slug}.sh"
    export ACTIONS_RUNNER_HOOK_JOB_COMPLETED="${APP_ROOT}/hooks/job-completed-${slug}.sh"
    exec ./run.sh
  ) >> "${runner_log}" 2>&1 &
  pid=$!
  printf '%s\n' "${pid}" > "${STATE_DIR}/runner-${slug}.pid"
  printf '%s\n' "${log_offset}" > "${STATE_DIR}/runner-${slug}.log-offset"
  printf '%s\n' "$(date +%s)" > "${STATE_DIR}/runner-${slug}.listener-start-epoch"
  rm -f "${STATE_DIR}/runner-${slug}.acquire-seen-epoch"
  RUNNER_PIDS+=("${pid}")

  sleep "${RUNNER_STARTUP_GRACE_SECONDS}"
  if ! kill -0 "${pid}" 2>/dev/null; then
    wait "${pid}" 2>/dev/null || true
    rm -f "${STATE_DIR}/runner-${slug}.pid" "${STATE_DIR}/runner-${slug}.online"
    printf '%s\n' "Runner process exited during startup. Open the runner log for the current error." > "${error_file}"
    write_runner_runtime_state "${slug}" "${repo}" "error" "persistent" "$(cat "${error_file}")"
    log "runner ${runner_name} exited during startup"
    return 1
  fi

  if runner_log_ready_since "${runner_log}" "${log_offset}"; then
    printf '%s\n' "1" > "${STATE_DIR}/runner-${slug}.online"
    write_runner_runtime_state "${slug}" "${repo}" "online" "persistent" "Listening for GitHub Actions jobs"
    activity "runner" "Runner online: ${repo}"
  else
    rm -f "${STATE_DIR}/runner-${slug}.online"
    write_runner_runtime_state "${slug}" "${repo}" "connecting" "persistent" "Runner process is alive; waiting for GitHub connection"
    activity "runner" "Runner connecting: ${repo}"
  fi
}

refresh_runner_readiness() {
  local repo_file slug pid_file pid runner_log offset_file offset repo runtime_file phase
  shopt -s nullglob
  local repo_files=("${STATE_DIR}"/runner-*.repo)
  shopt -u nullglob
  for repo_file in "${repo_files[@]}"; do
    slug="${repo_file##*/runner-}"; slug="${slug%.repo}"
    repo="$(cat "${repo_file}" 2>/dev/null || true)"
    pid_file="${STATE_DIR}/runner-${slug}.pid"
    runner_log="${STORAGE_ROOT}/logs/runner-${slug}.log"
    offset_file="${STATE_DIR}/runner-${slug}.log-offset"
    runtime_file="${STATE_DIR}/runner-${slug}.runtime.json"
    [[ -f "${pid_file}" ]] || continue
    pid="$(cat "${pid_file}" 2>/dev/null || true)"
    [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null || continue
    offset="$(cat "${offset_file}" 2>/dev/null || echo 0)"
    if [[ ! -f "${STATE_DIR}/runner-${slug}.online" ]] && runner_log_ready_since "${runner_log}" "${offset}"; then
      printf '%s\n' "1" > "${STATE_DIR}/runner-${slug}.online"
      write_runner_runtime_state "${slug}" "${repo}" "online" "persistent" "Listening for GitHub Actions jobs"
      activity "runner" "Runner online: ${repo}"
    fi
  done
}

write_status() {
  refresh_runner_readiness || true
  local docker_online=false compose_online=false configured=0 online=0 disk_total="—" disk_used="—" disk_pct=0 runner_summary="Runner not configured"
  local repo_file slug pid_file pid

  docker info >/dev/null 2>&1 && docker_online=true
  [[ -f "${DEPENDENCY_READY_FILE}" ]] && compose_online=true

  shopt -s nullglob
  local repo_files=("${STATE_DIR}"/runner-*.repo)
  configured="${#repo_files[@]}"
  for repo_file in "${repo_files[@]}"; do
    slug="${repo_file##*/runner-}"; slug="${slug%.repo}"
    pid_file="${STATE_DIR}/runner-${slug}.pid"
    [[ -f "${pid_file}" ]] || continue
    pid="$(cat "${pid_file}" 2>/dev/null || true)"
    [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null && [[ -f "${STATE_DIR}/runner-${slug}.online" ]] && online=$((online + 1))
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
    --argjson compose_online "${compose_online}" \
    --arg disk_used "${disk_used}" \
    --arg disk_total "${disk_total}" \
    --argjson disk_used_percent "${disk_pct:-0}" \
    --arg disk_path "${STORAGE_ROOT}" \
    --argjson cleanup_interval_days "$((CLEANUP_INTERVAL_HOURS / 24))" \
    --argjson cache_max_age_days "${CACHE_MAX_AGE_DAYS}" \
    --arg runtime_version "${RUNTIME_VERSION}" \
    --arg manager_build "${FORGECORE_MANAGER_BUILD}" \
    --argjson manager_started_epoch "${MANAGER_STARTED_EPOCH}" \
    --argjson status_epoch "$(date +%s)" \
    '{runner_online:$runner_online,runner_name:$runner_name,docker_online:$docker_online,compose_online:$compose_online,disk_used:$disk_used,disk_total:$disk_total,disk_used_percent:$disk_used_percent,disk_path:$disk_path,cleanup_interval_days:$cleanup_interval_days,cache_max_age_days:$cache_max_age_days,runtime_version:$runtime_version,manager_build:$manager_build,manager_started_epoch:$manager_started_epoch,status_epoch:$status_epoch}' \
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
  rm -f "${STATE_DIR}"/runner-*.pid "${STATE_DIR}"/runner-*.online "${STATE_DIR}"/runner-*.listener-start-epoch "${STATE_DIR}"/runner-*.acquire-seen-epoch
}

start_all_runners() {
  local app_file executor repo slug request_file
  declare -A seen_repositories=()
  rm -f "${STATE_DIR}"/runner-*.pid "${STATE_DIR}"/runner-*.name "${STATE_DIR}"/runner-*.repo "${STATE_DIR}"/runner-*.online

  shopt -s nullglob
  local app_configs=("${APP_CONFIG_DIR}"/*.json)
  shopt -u nullglob

  for app_file in "${app_configs[@]}"; do
    executor="$(jq -r '.build.executor // empty' "${app_file}" 2>/dev/null || true)"
    [[ "${executor}" == "github-actions" ]] || continue
    repo="$(jq -r '.source.repository // empty' "${app_file}" 2>/dev/null || true)"
    [[ "${repo}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || { log "invalid GitHub Actions App repository in ${app_file}"; continue; }
    slug="$(slugify "${repo}")"
    [[ -z "${seen_repositories[${slug}]:-}" ]] || continue
    seen_repositories["${slug}"]=1
    request_file="${RUNNER_REQUEST_DIR}/${slug}.json"
    start_runner_for_repository "${repo}" "${request_file}" || true
  done

  if (( ${#RUNNER_PIDS[@]} == 0 )); then
    log "No App-owned GitHub Actions runner is ready."
  fi
}

reload_runners() {
  local reason="${1:-runner reload requested}"
  log "${reason}"
  activity "runner" "${reason}"
  stop_runners
  normalize_app_permissions
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
  if [[ -n "${DEPENDENCY_PID}" ]]; then
    kill "${DEPENDENCY_PID}" 2>/dev/null || true
    wait "${DEPENDENCY_PID}" 2>/dev/null || true
  fi
}
trap shutdown_all TERM INT EXIT

main() {
prepare_paths
normalize_app_permissions
write_service_error "ForgeCore runner manager is starting"
log "ForgeCore runner manager ${RUNTIME_VERSION} booting"
activity "runner" "Runner manager ${RUNTIME_VERSION} booting"
load_config
rm -f "${RELOAD_FILE}"
log "ForgeCore runner manager ${RUNTIME_VERSION} control plane ready"
rm -f "${STATE_DIR}/runner-service.error"
activity "runner" "Runner manager ${RUNTIME_VERSION} control plane ready"
status_loop &
STATUS_PID=$!
dependency_loop &
DEPENDENCY_PID=$!

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
    if (( ${#RUNNER_PIDS[@]} == 0 )); then
      log "automatic recovery stopped because no runnable persistent identity is available"
      activity "runner" "Automatic recovery stopped; repair is required"
    fi
    sleep 5
    continue
  fi

  watchdog_reason="$(runner_watchdog_recycle_reason || true)"
  if [[ -n "${watchdog_reason}" ]]; then
    log "${watchdog_reason}"
    activity "runner" "${watchdog_reason}"
    sleep 2
    reload_runners "${watchdog_reason}"
    sleep 2
    continue
  fi

  sleep 2
done
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
