# ForgeCore Umbrel package

This directory is the self-contained source package that becomes `olympus-forgecore` for live Umbrel testing.

ForgeCore is the source of truth; this Olympus directory is the downstream Umbrel distribution package.
Changes are made in `Jojje84/ForgeCore` first and then synchronized here with source provenance recorded in `SOURCE_COMMIT`.

Beta 32 uses the standard `runners/<repository>` layout and migrates the working beta31 identity automatically without asking for another token. The Settings page now hides registration controls while a runner is healthy, separates listener connectivity from verified job execution, and the runner manager watches the real Actions diagnostic log for broker/session stalls.



The approved ForgeCore anvil remains unchanged. The canonical raster asset is `assets/forgecore-logo.png`; `icon.svg`, the dashboard-served icon and the fallback icon must all match it.

The dashboard is the primary control surface instead of SSH:

- Overview with runner, Docker, Compose, disk and cleanup status
- real last-cleanup and next-cleanup scheduling
- repository runner setup and repair with short-lived GitHub registration tokens; the repository name becomes both the runner name and the only custom label
- runner-manager restart with completion feedback
- editable cleanup interval, cache retention, workspace retention, disk threshold and BuildKit retention
- persistent runner-manager, cleanup and per-runner logs
- recent ForgeCore runtime activity
- About view that documents the package's actual capabilities and security boundaries

The dashboard uses the same ForgeCore logo as the Umbrel app and deliberately does not show optional QEMU support as "running" unless it is actually enabled.

Runtime code that must refresh during an Umbrel update is shipped through root-level `*.template` files, because Umbrel's legacy update path refreshes those files while arbitrary nested `data/` files are not update-safe.

Contents:

- `umbrel-app.yml` — Umbrel metadata and capability description
- `docker-compose.yml` — isolated Docker, runner manager, cleanup and dashboard services
- `exports.sh` — resolves and persists the verified external ForgeCore storage path before Umbrel start/update
- `runner-manager.b64.template` — update-safe runner manager payload
- `cleanup-loop.b64.template` — update-safe cleanup payload
- `dashboard-server.b64.template` — update-safe dashboard/API payload
- `data/bin/` — readable source copies of runtime scripts
- `assets/forgecore-logo.png` — canonical approved ForgeCore anvil artwork
- `icon.svg` — self-contained Umbrel icon generated from the canonical artwork
- `data/www/icon.svg` — fallback copy, required to be byte-identical to `icon.svg`

Heavy CI data remains on the configured external ForgeCore storage root. The runner never mounts Umbrel's host Docker socket.


Beta 36 adds a pre-manager bootstrap that repairs Umbrel-created root-owned app data before the uid-1001 GitHub runner starts, validates the rendered runner runtime artifact, and writes a persistent Runner bootstrap log before manager startup. The integration tests now reproduce Umbrel's real template rendering and root-owned app-data state.