# ForgeCore Umbrel package

This directory is the complete, update-safe Umbrel package source for ForgeCore.

ForgeCore is the source of truth; `olympus-forgecore` in the Olympus Community App Store is a distribution copy produced from a validated ForgeCore release.

## Runtime model

The package runs separate services for:

- ForgeCore dashboard and Control API
- repository-scoped GitHub Actions runner management
- isolated GitHub Actions Docker
- native ForgeCore worker
- isolated native build Docker
- cleanup and retention

Heavy runtime data stays on the configured external ForgeCore storage root. CI jobs never receive Umbrel's host Docker socket.

## Update-safe payloads

Umbrel updates do not reliably refresh arbitrary persisted nested files. Runtime code and dashboard HTML that must update are therefore shipped as root-level Base64 templates and rendered into app data during package bootstrap.

The readable source copies remain under `data/bin/` and `data/www/`; package validation requires the templates to decode byte-identically to those sources.

## Contents

- `umbrel-app.yml` — Umbrel metadata
- `docker-compose.yml` — service and isolation boundaries
- `exports.sh` — external-storage resolution/bootstrap
- `runner-manager.b64.template` — update-safe runner manager
- `cleanup-loop.b64.template` — update-safe cleanup service
- `dashboard-server.b64.template` — update-safe Control API/dashboard server
- `dashboard-v2.b64.template` — update-safe dashboard HTML
- `native-worker.b64.template` — update-safe native worker
- `isolated-runtime.b64.template` — update-safe isolated build runtime
- `data/bin/` — readable runtime source copies
- `data/www/` — live dashboard source and icon
- `assets/forgecore-logo.png` — canonical ForgeCore artwork
- `icon.svg` — Umbrel icon generated from the canonical artwork

## Administration

The dashboard uses six primary areas: Overview, Apps, Runners, System, Logs & Activity, and About. Apps groups application management with cross-App Jobs and Releases; normal Delivery lives inside each selected App. Reusable delivery rules remain an advanced implementation detail. Runners owns ForgeCore Native and repository-scoped GitHub runner operations. System groups runtime/storage health and Settings. Logs & Activity groups persistent logs and Audit history. About remains directly accessible from the primary navigation.

Dashboard live state is delivered with Server-Sent Events from the Control API, with automatic browser reconnection instead of a fixed refresh timer. App Source setup can connect a GitHub account using Device Flow and discover accessible repositories when the ForgeCore GitHub App client ID is configured.

Older installations are upgraded by narrow one-time importers. There is no parallel v1 dashboard or active v1 configuration runtime.
