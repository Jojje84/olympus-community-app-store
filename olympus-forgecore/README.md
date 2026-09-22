# ForgeCore Beta

ForgeCore Beta is the live Umbrel test package for ForgeCore.

Before installing, make sure the external ForgeCore storage directory exists at:

```text
/mnt/forgecore
```

The package deliberately refuses to create that host path automatically. This prevents CI data from silently falling back to the Umbrel system disk.

ForgeCore source development remains on the `feat/forgecore-v1-runtime` branch in `Jojje84/ForgeCore`.
