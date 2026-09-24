# ForgeCore Umbrel package

This directory is the complete, update-safe Umbrel package source for ForgeCore.

ForgeCore is the source of truth; `olympus-forgecore` in the Olympus Community App Store is a distribution copy produced from a validated ForgeCore release.

## Runtime model

The package runs separate services for:

- ForgeCore dashboard and Control API
- App-owned GitHub Actions runner management
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

The dashboard is the normal administration surface. Apps own repositories, executor selection, runner connections, output and publishing. Publishing connection setup is opened from the App when needed. All Jobs and All Releases are aggregate history views. Infrastructure reports shared runtime capacity and health. ForgeCore Settings contains only installation runtime/storage/security/backup policy.

Older installations are upgraded by narrow one-time importers. There is no parallel v1 dashboard or active v1 configuration runtime.
