# ForgeCore Beta

ForgeCore Beta is the live Umbrel test package for ForgeCore.

This Beelink installation uses the dedicated external HDD:

```text
/home/umbrel/umbrel/external/HDD/ForgeCore
```

Before installing, create the directory and marker:

```bash
mkdir -p /home/umbrel/umbrel/external/HDD/ForgeCore
touch /home/umbrel/umbrel/external/HDD/ForgeCore/.forgecore-external
```

The CI Docker engine refuses to start without that marker, so an unmounted
external disk cannot silently redirect ForgeCore's heavy data to the system disk.

ForgeCore source development remains on the `feat/forgecore-v1-runtime`
branch in `Jojje84/ForgeCore`.
