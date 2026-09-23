#!/usr/bin/env python3
import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "umbrel" if (ROOT / "umbrel").is_dir() else ROOT
DASHBOARD = PACKAGE_ROOT / "data" / "bin" / "dashboard-server.py"

spec = importlib.util.spec_from_file_location("forgecore_dashboard", DASHBOARD)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    module.RD = root / "app" / "config" / "runners"
    module.ST = root / "app" / "state"
    module.RUNNER_ENGINE = root / "storage" / "runners" / "v2"
    module.RD.mkdir(parents=True, exist_ok=True)
    module.ST.mkdir(parents=True, exist_ok=True)

    repo = "Jojje84/ForgeCore"
    slug = module.slug(repo)
    runner_dir = module.RUNNER_ENGINE / slug
    runner_dir.mkdir(parents=True, exist_ok=True)
    identity = runner_dir / ".runner"
    identity.write_text(json.dumps({"AgentId": 777, "Ephemeral": False}) + "\n", encoding="utf-8")

    blocked = False
    try:
        module.save_runner({
            "repository": repo,
            "token": "accidental-registration-token-1234567890",
        })
    except module.RunnerConflictError:
        blocked = True

    if not blocked:
        raise SystemExit("existing runner identity was not protected from accidental token replacement")
    if (module.RD / f"{slug}.env").exists():
        raise SystemExit("blocked replacement still wrote runner config")
    saved_identity = json.loads(identity.read_text(encoding="utf-8"))
    if saved_identity.get("AgentId") != 777:
        raise SystemExit("blocked replacement modified the saved runner identity")

    module.save_runner({
        "repository": repo,
        "token": "confirmed-registration-token-1234567890",
        "repair_existing": True,
    })
    config = module.RD / f"{slug}.env"
    if not config.exists():
        raise SystemExit("confirmed Repair did not create runner config")
    text = config.read_text(encoding="utf-8")
    if 'REGISTRATION_TOKEN="confirmed-registration-token-1234567890"' not in text:
        raise SystemExit("confirmed Repair did not persist the one-time token")
    if not (module.ST / "reload-runners.request").exists():
        raise SystemExit("confirmed Repair did not request runner reload")

    second = "Jojje84/NewProject"
    second_slug = module.slug(second)
    module.save_runner({
        "repository": second,
        "token": "new-runner-registration-token-1234567890",
    })
    if not (module.RD / f"{second_slug}.env").exists():
        raise SystemExit("new unregistered repository could not be added")

print("ForgeCore dashboard accidental token guard: OK")
