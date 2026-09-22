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
diag_dir="${tmp}/runner/_diag"
mkdir -p "${diag_dir}"

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

listener_start="$(date +%s)"
printf '%s\n' "[RUNNER] Acknowledging runner request 'diag-job'." > "${diag_dir}/Runner_test.log"
! runner_diag_watchdog_reason "test" "${tmp}/runner" "${listener_start}" >/dev/null
sleep 2
test "$(runner_diag_watchdog_reason "test" "${tmp}/runner" "${listener_start}")" = "acquire-stall"

printf '%s\n' "RunnerSessionInvalid" > "${diag_dir}/Runner_test.log"
test "$(runner_diag_watchdog_reason "test" "${tmp}/runner" "${listener_start}")" = "session-invalid"

echo "ForgeCore runner watchdog tests: OK"
