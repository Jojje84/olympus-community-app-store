# ForgeCore Beta

ForgeCore Beta is the live Umbrel test package for ForgeCore.

The current Beelink test installation uses the dedicated external HDD:

```text
/home/umbrel/umbrel/external/HDD/ForgeCore
```

Before first installation, create the directory and marker:

```bash
mkdir -p /home/umbrel/umbrel/external/HDD/ForgeCore
touch /home/umbrel/umbrel/external/HDD/ForgeCore/.forgecore-external
```

The storage marker prevents ForgeCore from silently placing heavy CI data on the system disk if the expected external storage is unavailable.

Normal administration is dashboard-first. The dashboard can add or repair GitHub repository runners, show per-runner/Docker/storage health, restart the runner manager, trigger cleanup with queued/running/completed feedback, and summarize the package capabilities. Short-lived GitHub registration tokens are cleared from repository config after registration.

ForgeCore source development remains on the `feat/forgecore-v1-runtime` branch in `Jojje84/ForgeCore`.
