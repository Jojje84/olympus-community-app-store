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

The marker prevents ForgeCore from silently redirecting heavy CI data to the system disk when the expected external storage is unavailable.

Beta 18 is dashboard-first. The dashboard has Overview, Settings, Logs and About views; runner setup/repair; runner-manager restart; cleanup queued/running/completed feedback; editable cleanup and retention settings; persistent runner/cleanup logs; recent ForgeCore activity; Docker/Compose/storage health; and a complete capability summary.

Normal runner setup asks only for the GitHub repository and a short-lived registration token. ForgeCore automatically uses the repository name as both the runner name and its single custom label. For example, `Jojje84/ForgeCore` becomes runner `ForgeCore` with the custom label `ForgeCore`.

ForgeCore uses the same glowing orange anvil logo across the Umbrel app and dashboard. Short-lived GitHub registration tokens are cleared from repository config after registration. ForgeCore's isolated CI Docker engine does not mount Umbrel's host Docker socket.

The optional QEMU/binfmt helper exists in the ForgeCore source tree but is not automatically enabled by the Umbrel package.

ForgeCore source development remains on the `feat/forgecore-v1-runtime` branch in `Jojje84/ForgeCore`.

Beta 18 is the reference-UI release. It keeps the exact approved glowing orange anvil across the Umbrel app, dashboard and favicon, aligns the dashboard typography and proportions to the approved mockup, makes the repository-name-only runner label visible in the UI, and keeps cleanup progress observable from queued through completion.
