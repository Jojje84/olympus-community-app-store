# ForgeCore Beta host-storage resolver for Umbrel.
#
# This beta is intentionally isolated from the existing ForgeCore installation.
# It never discovers or reuses legacy ForgeCore storage roots.

_forgecore_storage_marker=".forgecore-external"
_forgecore_storage_state_dir="${EXPORTS_APP_DIR}/data/state"
_forgecore_storage_choice_file="${EXPORTS_APP_DIR}/data/forgecore-storage-root"
_forgecore_storage_error_file="${_forgecore_storage_state_dir}/storage-resolution.error"

_forgecore_storage_valid() {
  [ -n "${1:-}" ] && [ -d "$1" ] && [ -f "$1/${_forgecore_storage_marker}" ]
}

_forgecore_storage_pick=""
_forgecore_storage_source=""

# 1. Respect an explicitly supplied beta storage path.
if _forgecore_storage_valid "${FORGECORE_STORAGE_ROOT:-}"; then
  _forgecore_storage_pick="${FORGECORE_STORAGE_ROOT}"
  _forgecore_storage_source="environment"
fi

# 2. Reuse only a path previously selected by this beta app's own APP_DATA_DIR.
if [ -z "${_forgecore_storage_pick}" ] && [ -s "${_forgecore_storage_choice_file}" ]; then
  IFS= read -r _forgecore_saved_path < "${_forgecore_storage_choice_file}" || _forgecore_saved_path=""
  if _forgecore_storage_valid "${_forgecore_saved_path}"; then
    _forgecore_storage_pick="${_forgecore_saved_path}"
    _forgecore_storage_source="saved"
  fi
fi

# 3. Reuse an already initialized ForgeCore-Beta directory only.
if [ -z "${_forgecore_storage_pick}" ]; then
  _forgecore_match_count=0
  _forgecore_match=""
  for _forgecore_candidate in "${UMBREL_ROOT}"/external/*/ForgeCore-Beta "${UMBREL_ROOT}"/external/*/forgecore-beta; do
    if _forgecore_storage_valid "${_forgecore_candidate}"; then
      _forgecore_match="${_forgecore_candidate}"
      _forgecore_match_count=$((_forgecore_match_count + 1))
    fi
  done
  if [ "${_forgecore_match_count}" -eq 1 ]; then
    _forgecore_storage_pick="${_forgecore_match}"
    _forgecore_storage_source="beta-storage"
  fi
fi

# 4. On a host with exactly one external drive, initialize a brand-new beta
#    directory on that drive. Never inspect or copy the old ForgeCore directory.
if [ -z "${_forgecore_storage_pick}" ]; then
  _forgecore_drive_count=0
  _forgecore_drive=""
  for _forgecore_external in "${UMBREL_ROOT}"/external/*; do
    if [ -d "${_forgecore_external}" ]; then
      _forgecore_drive="${_forgecore_external}"
      _forgecore_drive_count=$((_forgecore_drive_count + 1))
    fi
  done
  if [ "${_forgecore_drive_count}" -eq 1 ]; then
    _forgecore_candidate="${_forgecore_drive}/ForgeCore-Beta"
    if mkdir -p "${_forgecore_candidate}" 2>/dev/null && touch "${_forgecore_candidate}/${_forgecore_storage_marker}" 2>/dev/null; then
      _forgecore_storage_pick="${_forgecore_candidate}"
      _forgecore_storage_source="beta-created"
    fi
  fi
fi

mkdir -p "${_forgecore_storage_state_dir}" "${EXPORTS_APP_DIR}/data" 2>/dev/null || true

if [ -n "${_forgecore_storage_pick}" ]; then
  export FORGECORE_STORAGE_ROOT="${_forgecore_storage_pick}"
  printf '%s\n' "${_forgecore_storage_pick}" > "${_forgecore_storage_choice_file}.tmp" 2>/dev/null \
    && mv -f "${_forgecore_storage_choice_file}.tmp" "${_forgecore_storage_choice_file}" 2>/dev/null \
    || true
  rm -f "${_forgecore_storage_error_file}" 2>/dev/null || true
  export FORGECORE_STORAGE_RESOLUTION="${_forgecore_storage_source}"
else
  export FORGECORE_STORAGE_ROOT="/mnt/forgecore-beta"
  export FORGECORE_STORAGE_RESOLUTION="unresolved"
  printf '%s\n' \
    "ForgeCore Beta could not select a clean external storage root. Configure a dedicated directory containing .forgecore-external; legacy ForgeCore storage is never reused." \
    > "${_forgecore_storage_error_file}" 2>/dev/null || true
fi

unset _forgecore_storage_marker _forgecore_storage_state_dir _forgecore_storage_choice_file
unset _forgecore_storage_error_file _forgecore_storage_pick _forgecore_storage_source
unset _forgecore_saved_path _forgecore_match_count _forgecore_match _forgecore_candidate
unset _forgecore_drive_count _forgecore_drive _forgecore_external
unset -f _forgecore_storage_valid 2>/dev/null || true
