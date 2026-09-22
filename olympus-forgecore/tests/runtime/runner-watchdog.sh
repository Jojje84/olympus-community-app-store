#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -d "${ROOT}/umbrel" ]]; then
  PACKAGE_ROOT="${ROOT}/umbrel"
else
  PACKAGE_ROOT="${ROOT}"
fi
export FORGECORE_RUNNER_ACQUIRE_STALL_SECONDS=1
source "${PACKAGE_ROOT}/data/bin/runner-manager.sh"

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT
log="${tmp}/runner.log"

printf '%s\n' "runner starting" > "${log}"
! runner_log_watchdog_reason "${log}" 0 >/dev/null

printf '%s\n' "[RUNNER] Acknowledging runner request 'abc'." >> "${log}"
! runner_log_watchdog_reason "${log}" 0 >/dev/null

touch -d '3 seconds ago' "${log}"
test "$(runner_log_watchdog_reason "${log}" 0)" = "acquire-stall"

printf '%s\n' "Running job: validate" >> "${log}"
printf '%s\n' "Job validate completed with result: Succeeded" >> "${log}"
test "$(runner_log_watchdog_reason "${log}" 0)" = "post-job"

offset="$(wc -c < "${log}")"
printf '%s\n' "fresh listener session" >> "${log}"
! runner_log_watchdog_reason "${log}" "${offset}" >/dev/null

echo "ForgeCore runner watchdog tests: OK"
