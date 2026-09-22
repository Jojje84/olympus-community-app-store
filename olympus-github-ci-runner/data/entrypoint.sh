#!/usr/bin/env bash
set -euo pipefail

RUNNER_DIR="/data/runner"
CONFIG_DIR="/data/config"
SETTINGS_FILE="${CONFIG_DIR}/settings.env"
TOKEN_FILE="${CONFIG_DIR}/registration-token"
COMPOSE_VERSION="5.5.1"
COMPOSE_SHA256="db1889184726840f75c4f9c001048430d4f25b3be3cb084d3ddd762bc0aed576"

mkdir -p "${RUNNER_DIR}" "${CONFIG_DIR}"

if [[ ! -x "${RUNNER_DIR}/run.sh" ]]; then
  echo "Seeding persistent GitHub Actions runner files..."
  cp -a /home/runner/. "${RUNNER_DIR}/"
fi

export HOME="${RUNNER_DIR}"
export DOCKER_CONFIG="${RUNNER_DIR}/.docker"
mkdir -p "${DOCKER_CONFIG}/cli-plugins"

COMPOSE_PLUGIN="${DOCKER_CONFIG}/cli-plugins/docker-compose"
if [[ ! -x "${COMPOSE_PLUGIN}" ]]; then
  echo "Installing pinned Docker Compose v${COMPOSE_VERSION}..."
  curl -fsSL     "https://github.com/docker/compose/releases/download/v${COMPOSE_VERSION}/docker-compose-linux-x86_64"     -o "${COMPOSE_PLUGIN}.tmp"
  echo "${COMPOSE_SHA256}  ${COMPOSE_PLUGIN}.tmp" | sha256sum -c -
  mv "${COMPOSE_PLUGIN}.tmp" "${COMPOSE_PLUGIN}"
  chmod +x "${COMPOSE_PLUGIN}"
fi

echo "Waiting for isolated Docker engine..."
until docker info >/dev/null 2>&1; do
  sleep 2
done

cd "${RUNNER_DIR}"

if [[ ! -f ".runner" ]]; then
  if [[ ! -f "${SETTINGS_FILE}" || ! -s "${TOKEN_FILE}" ]]; then
    cat <<'EOF'
GitHub CI Runner is installed but not registered yet.

SSH into Umbrel and run:
  bash ~/umbrel/app-data/olympus-github-ci-runner/data/configure.sh

Then restart the app from the Umbrel UI.
EOF
    exec sleep infinity
  fi

  # shellcheck disable=SC1090
  source "${SETTINGS_FILE}"

  : "${REPO_URL:?REPO_URL is missing from settings.env}"
  : "${RUNNER_NAME:=beelink-ci-01}"
  : "${RUNNER_LABELS:=beelink}"

  registration_token="$(cat "${TOKEN_FILE}")"

  ./config.sh     --unattended     --url "${REPO_URL}"     --token "${registration_token}"     --name "${RUNNER_NAME}"     --labels "${RUNNER_LABELS}"     --work "_work"     --replace

  rm -f "${TOKEN_FILE}"
fi

exec ./run.sh
