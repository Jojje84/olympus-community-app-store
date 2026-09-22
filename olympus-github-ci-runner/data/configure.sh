#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${SCRIPT_DIR}/config"
SETTINGS_FILE="${CONFIG_DIR}/settings.env"
TOKEN_FILE="${CONFIG_DIR}/registration-token"

mkdir -p "${CONFIG_DIR}"
chmod 700 "${CONFIG_DIR}"

printf 'GitHub repository URL [https://github.com/Jojje84/UniCore]: '
read -r repo_url
repo_url="${repo_url:-https://github.com/Jojje84/UniCore}"

printf 'Runner name [beelink-ci-01]: '
read -r runner_name
runner_name="${runner_name:-beelink-ci-01}"

printf 'Runner labels [beelink,unicore-build]: '
read -r runner_labels
runner_labels="${runner_labels:-beelink,unicore-build}"

printf 'Paste the short-lived GitHub runner registration token: '
read -rs registration_token
printf '\n'

if [[ -z "${registration_token}" ]]; then
  echo "Registration token cannot be empty." >&2
  exit 1
fi

cat >"${SETTINGS_FILE}" <<EOF
REPO_URL=${repo_url}
RUNNER_NAME=${runner_name}
RUNNER_LABELS=${runner_labels}
EOF

printf '%s' "${registration_token}" >"${TOKEN_FILE}"
chmod 600 "${SETTINGS_FILE}" "${TOKEN_FILE}"

cat <<EOF

Configuration saved.

Repository: ${repo_url}
Runner:     ${runner_name}
Labels:     ${runner_labels}

Restart "GitHub CI Runner" from the Umbrel UI.
The registration token is deleted automatically after successful registration.
EOF
