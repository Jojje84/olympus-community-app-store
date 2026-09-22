# ForgeCore host-storage resolver for Umbrel.
#
# Umbrel replaces docker-compose.yml during app updates. Any host-specific bind
# mount edited directly into that file is therefore lost. This export is sourced
# by Umbrel before Compose is evaluated, so the external ForgeCore path survives
# package updates without modifying docker-compose.yml.

_forgecore_storage_marker=".forgecore-external"
_forgecore_storage_state_dir="${EXPORTS_APP_DIR}/data/state"
_forgecore_storage_choice_file="${EXPORTS_APP_DIR}/data/forgecore-storage-root"
_forgecore_storage_error_file="${_forgecore_storage_state_dir}/storage-resolution.error"

_forgecore_storage_valid() {
  [ -n "${1:-}" ] && [ -d "$1" ] && [ -f "$1/${_forgecore_storage_marker}" ]
}

_forgecore_storage_pick=""
_forgecore_storage_source=""

# 1. Respect an explicitly supplied path when it still points at a verified
#    ForgeCore storage root.
if _forgecore_storage_valid "${FORGECORE_STORAGE_ROOT:-}"; then
  _forgecore_storage_pick="${FORGECORE_STORAGE_ROOT}"
  _forgecore_storage_source="environment"
fi

# 2. Reuse the last successfully resolved host path. This file is under
#    APP_DATA_DIR/data and is not replaced by Umbrel app updates.
if [ -z "${_forgecore_storage_pick}" ] && [ -s "${_forgecore_storage_choice_file}" ]; then
  IFS= read -r _forgecore_saved_path < "${_forgecore_storage_choice_file}" || _forgecore_saved_path=""
  if _forgecore_storage_valid "${_forgecore_saved_path}"; then
    _forgecore_storage_pick="${_forgecore_saved_path}"
    _forgecore_storage_source="saved"
  fi
fi

# 3. Recover legacy/manual installations by discovering a verified ForgeCore
#    directory on Umbrel's external drives. Only auto-select when exactly one
#    marked directory exists; never guess between multiple disks.
if [ -z "${_forgecore_storage_pick}" ]; then
  _forgecore_match_count=0
  _forgecore_match=""
  for _forgecore_candidate in "${UMBREL_ROOT}"/external/*/ForgeCore "${UMBREL_ROOT}"/external/*/forgecore; do
    if _forgecore_storage_valid "${_forgecore_candidate}"; then
      _forgecore_match="${_forgecore_candidate}"
      _forgecore_match_count=$((_forgecore_match_count + 1))
    fi
  done
  if [ "${_forgecore_match_count}" -eq 1 ]; then
    _forgecore_storage_pick="${_forgecore_match}"
    _forgecore_storage_source="external-discovery"
  fi
fi

# 4. Support an already initialized legacy default path.
if [ -z "${_forgecore_storage_pick}" ] && _forgecore_storage_valid "/mnt/forgecore"; then
  _forgecore_storage_pick="/mnt/forgecore"
  _forgecore_storage_source="legacy-default"
fi

mkdir -p "${_forgecore_storage_state_dir}" "${EXPORTS_APP_DIR}/data" 2>/dev/null || true

if [ -n "${_forgecore_storage_pick}" ]; then
  export FORGECORE_STORAGE_ROOT="${_forgecore_storage_pick}"
  printf '%s\n' "${_forgecore_storage_pick}" > "${_forgecore_storage_choice_file}.tmp" 2>/dev/null     && mv -f "${_forgecore_storage_choice_file}.tmp" "${_forgecore_storage_choice_file}" 2>/dev/null     || true
  rm -f "${_forgecore_storage_error_file}" 2>/dev/null || true
  export FORGECORE_STORAGE_RESOLUTION="${_forgecore_storage_source}"
else
  # Leave a deterministic fallback for Compose, but record the actual reason in
  # app data so the dashboard can report it. Docker/runner keep their marker
  # guard and will not silently create heavy CI data on the wrong disk.
  export FORGECORE_STORAGE_ROOT="/mnt/forgecore"
  export FORGECORE_STORAGE_RESOLUTION="unresolved"
  printf '%s\n'     "ForgeCore could not find a verified external storage root. Expected a .forgecore-external marker under an existing ForgeCore storage directory."     > "${_forgecore_storage_error_file}" 2>/dev/null || true
fi

unset _forgecore_storage_marker _forgecore_storage_state_dir _forgecore_storage_choice_file
unset _forgecore_storage_error_file _forgecore_storage_pick _forgecore_storage_source
unset _forgecore_saved_path _forgecore_match_count _forgecore_match _forgecore_candidate
unset -f _forgecore_storage_valid 2>/dev/null || true
