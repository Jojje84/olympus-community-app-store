# ForgeCore Beta host-storage resolver for Umbrel.
#
# This beta is intentionally isolated from the existing ForgeCore installation.
# It never discovers or reuses legacy ForgeCore storage roots.

_forgecore_storage_marker=".forgecore-external"
_forgecore_storage_state_dir="${EXPORTS_APP_DIR}/data/state"
_forgecore_storage_choice_file="${EXPORTS_APP_DIR}/data/forgecore-storage-root"
_forgecore_storage_candidates_file="${_forgecore_storage_state_dir}/storage-candidates.tsv"
_forgecore_storage_error_file="${_forgecore_storage_state_dir}/storage-resolution.error"
_forgecore_internal_root="${EXPORTS_APP_DIR}/data/storage"

_forgecore_storage_valid() {
  [ -n "${1:-}" ] && [ -d "$1" ] && [ -f "$1/${_forgecore_storage_marker}" ]
}

mkdir -p "${_forgecore_storage_state_dir}" "${EXPORTS_APP_DIR}/data" 2>/dev/null || true
if mkdir -p "${_forgecore_internal_root}" 2>/dev/null; then
  touch "${_forgecore_internal_root}/${_forgecore_storage_marker}" 2>/dev/null || true
fi

_forgecore_candidates_tmp="${_forgecore_storage_candidates_file}.tmp"
: > "${_forgecore_candidates_tmp}" 2>/dev/null || true
printf 'internal\tInternal / Umbrel app data\t%s\n' "${_forgecore_internal_root}" >> "${_forgecore_candidates_tmp}" 2>/dev/null || true

_forgecore_drive_count=0
_forgecore_drive=""
for _forgecore_external in "${UMBREL_ROOT}"/external/*; do
  if [ -d "${_forgecore_external}" ]; then
    _forgecore_drive="${_forgecore_external}"
    _forgecore_drive_count=$((_forgecore_drive_count + 1))
    _forgecore_candidate="${_forgecore_external}/ForgeCore-Beta"
    _forgecore_drive_label="$(basename "${_forgecore_external}")"
    printf 'external\tExternal · %s\t%s\n' "${_forgecore_drive_label}" "${_forgecore_candidate}" >> "${_forgecore_candidates_tmp}" 2>/dev/null || true
  fi
done
mv -f "${_forgecore_candidates_tmp}" "${_forgecore_storage_candidates_file}" 2>/dev/null || true

_forgecore_storage_allowed() {
  _forgecore_allowed_target="${1:-}"
  [ -n "${_forgecore_allowed_target}" ] || return 1
  while IFS="$(printf '\t')" read -r _forgecore_kind _forgecore_label _forgecore_path; do
    if [ "${_forgecore_path}" = "${_forgecore_allowed_target}" ]; then
      return 0
    fi
  done < "${_forgecore_storage_candidates_file}"
  return 1
}

_forgecore_initialize_choice() {
  _forgecore_init_target="${1:-}"
  _forgecore_storage_allowed "${_forgecore_init_target}" || return 1
  mkdir -p "${_forgecore_init_target}" 2>/dev/null || return 1
  touch "${_forgecore_init_target}/${_forgecore_storage_marker}" 2>/dev/null || return 1
  _forgecore_storage_valid "${_forgecore_init_target}"
}

_forgecore_storage_pick=""
_forgecore_storage_source=""

# 1. Respect an explicitly supplied verified storage path.
if _forgecore_storage_valid "${FORGECORE_STORAGE_ROOT:-}"; then
  _forgecore_storage_pick="${FORGECORE_STORAGE_ROOT}"
  _forgecore_storage_source="environment"
fi

# 2. Reuse only a path previously selected by this beta app.
if [ -z "${_forgecore_storage_pick}" ] && [ -s "${_forgecore_storage_choice_file}" ]; then
  IFS= read -r _forgecore_saved_path < "${_forgecore_storage_choice_file}" || _forgecore_saved_path=""
  if _forgecore_storage_allowed "${_forgecore_saved_path}"; then
    if ! _forgecore_storage_valid "${_forgecore_saved_path}"; then
      _forgecore_initialize_choice "${_forgecore_saved_path}" || true
    fi
    if _forgecore_storage_valid "${_forgecore_saved_path}"; then
      _forgecore_storage_pick="${_forgecore_saved_path}"
      _forgecore_storage_source="saved"
    fi
  fi
fi

# 3. Reuse exactly one already initialized beta directory.
if [ -z "${_forgecore_storage_pick}" ]; then
  _forgecore_match_count=0
  _forgecore_match=""
  while IFS="$(printf '\t')" read -r _forgecore_kind _forgecore_label _forgecore_path; do
    if [ "${_forgecore_kind}" = "external" ] && _forgecore_storage_valid "${_forgecore_path}"; then
      _forgecore_match="${_forgecore_path}"
      _forgecore_match_count=$((_forgecore_match_count + 1))
    fi
  done < "${_forgecore_storage_candidates_file}"
  if [ "${_forgecore_match_count}" -eq 1 ]; then
    _forgecore_storage_pick="${_forgecore_match}"
    _forgecore_storage_source="beta-storage"
  fi
fi

# 4. If there is exactly one external drive, initialize and use it automatically.
if [ -z "${_forgecore_storage_pick}" ] && [ "${_forgecore_drive_count}" -eq 1 ]; then
  _forgecore_candidate="${_forgecore_drive}/ForgeCore-Beta"
  if _forgecore_initialize_choice "${_forgecore_candidate}"; then
    _forgecore_storage_pick="${_forgecore_candidate}"
    _forgecore_storage_source="beta-created"
  fi
fi

# 5. With zero or multiple external drives, use isolated Umbrel app data by
#    default. Multiple external drives are exposed to the dashboard for an
#    explicit user choice; ForgeCore never guesses between them.
if [ -z "${_forgecore_storage_pick}" ] && _forgecore_storage_valid "${_forgecore_internal_root}"; then
  _forgecore_storage_pick="${_forgecore_internal_root}"
  _forgecore_storage_source="internal-default"
fi

if [ -n "${_forgecore_storage_pick}" ]; then
  export FORGECORE_STORAGE_ROOT="${_forgecore_storage_pick}"
  printf '%s\n' "${_forgecore_storage_pick}" > "${_forgecore_storage_choice_file}.tmp" 2>/dev/null \
    && mv -f "${_forgecore_storage_choice_file}.tmp" "${_forgecore_storage_choice_file}" 2>/dev/null \
    || true
  rm -f "${_forgecore_storage_error_file}" "${_forgecore_storage_state_dir}/storage-restart-required" 2>/dev/null || true
  export FORGECORE_STORAGE_RESOLUTION="${_forgecore_storage_source}"
else
  export FORGECORE_STORAGE_ROOT="/mnt/forgecore-beta"
  export FORGECORE_STORAGE_RESOLUTION="unresolved"
  printf '%s\n' \
    "ForgeCore Beta could not prepare internal storage or a selected external storage root. Check storage permissions before starting runner services." \
    > "${_forgecore_storage_error_file}" 2>/dev/null || true
fi

unset _forgecore_storage_marker _forgecore_storage_state_dir _forgecore_storage_choice_file
unset _forgecore_storage_candidates_file _forgecore_storage_error_file _forgecore_internal_root
unset _forgecore_candidates_tmp _forgecore_storage_pick _forgecore_storage_source _forgecore_saved_path
unset _forgecore_match_count _forgecore_match _forgecore_candidate _forgecore_drive_count _forgecore_drive
unset _forgecore_external _forgecore_drive_label _forgecore_allowed_target _forgecore_kind _forgecore_label
unset _forgecore_path _forgecore_init_target
unset -f _forgecore_storage_valid _forgecore_storage_allowed _forgecore_initialize_choice 2>/dev/null || true
