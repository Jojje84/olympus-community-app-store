#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -d "${ROOT}/umbrel" ]]; then
  PACKAGE_ROOT="${ROOT}/umbrel"
else
  PACKAGE_ROOT="${ROOT}"
fi
MANAGER="${PACKAGE_ROOT}/data/bin/runner-manager.sh"
DASHBOARD="${PACKAGE_ROOT}/data/bin/dashboard-server.py"

tmp="$(mktemp -d)"
cleanup() {
  if [[ -n "${TEST_RUNNER_PID:-}" ]]; then
    kill "${TEST_RUNNER_PID}" 2>/dev/null || true
    wait "${TEST_RUNNER_PID}" 2>/dev/null || true
  fi
  rm -rf "${tmp}"
}
trap cleanup EXIT

export FORGECORE_APP_ROOT="${tmp}/app"
export FORGECORE_STORAGE_ROOT="${tmp}/storage"
export FORGECORE_RUNNER_DIST_ROOT="${tmp}/dist"
export FORGECORE_RUNNER_STARTUP_GRACE_SECONDS="0.1"

mkdir -p   "${FORGECORE_APP_ROOT}/config/runners"   "${FORGECORE_APP_ROOT}/state"   "${FORGECORE_STORAGE_ROOT}/runners/jojje84-forgecore"   "${FORGECORE_STORAGE_ROOT}/logs"   "${FORGECORE_RUNNER_DIST_ROOT}"

runner_dir="${FORGECORE_STORAGE_ROOT}/runners/jojje84-forgecore"
config_file="${FORGECORE_APP_ROOT}/config/runners/jojje84-forgecore.env"

cat > "${FORGECORE_RUNNER_DIST_ROOT}/config.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" > config-args.txt
if [[ "${FAKE_CONFIG_FAIL:-0}" == "1" ]]; then
  echo "GitHub rejected clean registration in lifecycle test"
  exit 1
fi
printf '%s\n' '{"AgentId":123,"AgentName":"ForgeCore","DisableUpdate":true,"Ephemeral":false,"GitHubUrl":"https://github.com/Jojje84/ForgeCore","WorkFolder":"_work"}' > .runner
printf '%s\n' '{"scheme":"OAuth"}' > .credentials
SH
chmod +x "${FORGECORE_RUNNER_DIST_ROOT}/config.sh"

cat > "${FORGECORE_RUNNER_DIST_ROOT}/run.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
sleep "${FAKE_LISTEN_DELAY:-0}"
echo "Listening for Jobs"
trap 'exit 0' TERM INT
while true; do sleep 1; done
SH
chmod +x "${FORGECORE_RUNNER_DIST_ROOT}/run.sh"

# shellcheck source=/dev/null
source "${MANAGER}"

cat > "${config_file}" <<'EOF'
REPOSITORY="Jojje84/ForgeCore"
REGISTRATION_TOKEN="fresh-test-token"
EOF

FAKE_LISTEN_DELAY=0
export FAKE_LISTEN_DELAY
start_runner_from_config "${config_file}"

grep -Fq 'REGISTRATION_TOKEN=""' "${config_file}"
jq -e '.phase == "online" and .mode == "persistent"' "${FORGECORE_APP_ROOT}/state/runner-jojje84-forgecore.runtime.json" >/dev/null
test -f "${FORGECORE_APP_ROOT}/state/runner-jojje84-forgecore.online"
grep -Fq -- '--disableupdate' "${runner_dir}/config-args.txt"
grep -Fq -- '--no-default-labels' "${runner_dir}/config-args.txt"
grep -Fq -- '--labels ForgeCore' "${runner_dir}/config-args.txt"
TEST_RUNNER_PID="$(cat "${FORGECORE_APP_ROOT}/state/runner-jojje84-forgecore.pid")"
kill -0 "${TEST_RUNNER_PID}"
stop_runners
unset TEST_RUNNER_PID

# A normal manager reload must reuse the persistent identity without another token.
cat > "${FORGECORE_APP_ROOT}/config/forgecore.env" <<'EOF'
COMPOSE_VERSION="5.5.1"
COMPOSE_SHA256_X86_64="test"
COMPOSE_SHA256_AARCH64="test"
CLEANUP_INTERVAL_HOURS=168
CACHE_MAX_AGE_DAYS=14
EOF
FAKE_LISTEN_DELAY=0
export FAKE_LISTEN_DELAY
reload_runners "Test persistent restart"
grep -Fq 'REGISTRATION_TOKEN=""' "${config_file}"
jq -e '.phase == "online" and .mode == "persistent"' "${FORGECORE_APP_ROOT}/state/runner-jojje84-forgecore.runtime.json" >/dev/null
TEST_RUNNER_PID="$(cat "${FORGECORE_APP_ROOT}/state/runner-jojje84-forgecore.pid")"
kill -0 "${TEST_RUNNER_PID}"
stop_runners
unset TEST_RUNNER_PID

# A valid persistent identity may connect after startup; readiness must become online later.
cat > "${config_file}" <<'EOF'
REPOSITORY="Jojje84/ForgeCore"
REGISTRATION_TOKEN=""
EOF
FAKE_LISTEN_DELAY=0.5
export FAKE_LISTEN_DELAY
start_runner_from_config "${config_file}"
jq -e '.phase == "connecting" and .mode == "persistent"' "${FORGECORE_APP_ROOT}/state/runner-jojje84-forgecore.runtime.json" >/dev/null
sleep 0.7
refresh_runner_readiness
jq -e '.phase == "online"' "${FORGECORE_APP_ROOT}/state/runner-jojje84-forgecore.runtime.json" >/dev/null
TEST_RUNNER_PID="$(cat "${FORGECORE_APP_ROOT}/state/runner-jojje84-forgecore.pid")"
stop_runners
unset TEST_RUNNER_PID

# Old one-time identities must never be started silently.
printf '%s\n' '{"AgentId":123,"AgentName":"ForgeCore","Ephemeral":true}' > "${runner_dir}/.runner"
cat > "${config_file}" <<'EOF'
REPOSITORY="Jojje84/ForgeCore"
REGISTRATION_TOKEN=""
EOF
start_runner_from_config "${config_file}"
jq -e '.phase == "needs-repair" and .mode == "ephemeral"' "${FORGECORE_APP_ROOT}/state/runner-jojje84-forgecore.runtime.json" >/dev/null
test ! -f "${FORGECORE_APP_ROOT}/state/runner-jojje84-forgecore.pid"

# A failed registration must keep the short-lived token so the request is not silently lost.
printf '%s\n' 'not-json' > "${runner_dir}/.runner"
cat > "${config_file}" <<'EOF'
REPOSITORY="Jojje84/ForgeCore"
REGISTRATION_TOKEN="keep-this-token"
REPAIR_EXISTING="true"
EOF
export FAKE_CONFIG_FAIL=1
if start_runner_from_config "${config_file}"; then
  echo "expected failed fake registration" >&2
  exit 1
fi
unset FAKE_CONFIG_FAIL
grep -Fq 'REGISTRATION_TOKEN="keep-this-token"' "${config_file}"
jq -e '.phase == "error"' "${FORGECORE_APP_ROOT}/state/runner-jojje84-forgecore.runtime.json" >/dev/null
grep -Fq 'GitHub rejected clean registration in lifecycle test' "${FORGECORE_APP_ROOT}/state/runner-jojje84-forgecore.error"
grep -Fq 'GitHub rejected clean registration in lifecycle test' "${FORGECORE_STORAGE_ROOT}/logs/registration-jojje84-forgecore.log"

# Dashboard must parse the runner file even when it starts with a UTF-8 BOM and
# must persist repair phase/message in server-side state so refreshes do not erase it.
python3 - "${DASHBOARD}" "${tmp}" <<'PY'
import importlib.util
import json
import os
import sys
from pathlib import Path

dashboard_path = Path(sys.argv[1])
root = Path(sys.argv[2])
app = root / "dash-app"
storage = root / "dash-storage"
rd = app / "config" / "runners"
st = app / "state"
runner_dir = storage / "runners" / "jojje84-forgecore"
rd.mkdir(parents=True)
st.mkdir(parents=True)
runner_dir.mkdir(parents=True)

os.environ["FORGECORE_APP_ROOT"] = str(app)
os.environ["FORGECORE_STORAGE_ROOT"] = str(storage)
os.environ["FORGECORE_STORAGE_DISPLAY"] = "/external/ForgeCore"

(rd / "jojje84-forgecore.env").write_text(
    'REPOSITORY="Jojje84/ForgeCore"\nREGISTRATION_TOKEN=""\n',
    encoding="utf-8",
)
identity = {
    "AgentId": 123,
    "AgentName": "ForgeCore",
    "DisableUpdate": True,
    "Ephemeral": False,
}
(runner_dir / ".runner").write_text(json.dumps(identity), encoding="utf-8-sig")

spec = importlib.util.spec_from_file_location("forgecore_dashboard_test", dashboard_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

items = module.runners()
assert len(items) == 1, items
assert items[0]["mode"] == "persistent", items
assert items[0]["phase"] == "idle", items

try:
    module.save_runner({
        "repository": "Jojje84/ForgeCore",
        "token": "fresh-dashboard-token",
    })
except module.RunnerConflictError:
    pass
else:
    raise AssertionError("unconfirmed Repair unexpectedly replaced a persistent identity")
assert not (st / "reload-runners.request").exists()

module.save_runner({
    "repository": "Jojje84/ForgeCore",
    "token": "fresh-dashboard-token",
    "repair_existing": True,
})
items = module.runners()
assert items[0]["phase"] == "queued", items
assert "waiting for runner manager" in items[0]["message"].lower(), items
runtime = json.loads((st / "runner-jojje84-forgecore.runtime.json").read_text())
assert runtime["phase"] == "queued", runtime
assert (st / "reload-runners.request").exists()

# Simulate a full browser refresh: status is reconstructed from disk, not JS memory.
status = module.status()
runner = status["runners"][0]
assert runner["phase"] == "queued", runner
assert runner["mode"] == "persistent", runner
PY

echo "ForgeCore runner lifecycle tests: OK"
