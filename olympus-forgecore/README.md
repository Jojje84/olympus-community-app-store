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

Beta 15 is dashboard-first. The dashboard has Overview, Settings, Logs and About views; runner setup/repair; runner-manager restart; cleanup queued/running/completed feedback; editable cleanup and retention settings; persistent runner/cleanup logs; recent ForgeCore activity; Docker/Compose/storage health; and a complete capability summary.

Normal runner setup now asks only for the GitHub repository and a short-lived registration token. ForgeCore automatically derives the runner name and labels from the repository. For example, `Jojje84/ForgeCore` becomes runner `beelink-forgecore` with custom labels `beelink`, `forgecore` and `jojje84-forgecore`.

ForgeCore uses the same glowing orange anvil logo across the Umbrel app and dashboard. Short-lived GitHub registration tokens are cleared from repository config after registration. ForgeCore's isolated CI Docker engine does not mount Umbrel's host Docker socket.

The optional QEMU/binfmt helper exists in the ForgeCore source tree but is not automatically enabled by the Umbrel package.

ForgeCore source development remains on the `feat/forgecore-v1-runtime` branch in `Jojje84/ForgeCore`.

Beta 15 is a recovery release for installations that received the broken early beta 14 dashboard package. It republishes the validated repaired dashboard under a new version so Umbrel can offer a normal update.
