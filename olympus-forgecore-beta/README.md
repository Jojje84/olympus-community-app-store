# ForgeCore Runner Core Beta

ForgeCore Runner Core is a local-first self-hosted GitHub Actions runner manager for Umbrel.

## Beta 29

Beta 29 fixes repository workflow permissions and makes choosing your own local runner explicit.

- Workflow file access is verified per repository before Create, Rename, Delete or runner routing is enabled.
- If GitHub Actions can be listed but the connected GitHub App cannot read the actual workflow YAML, ForgeCore shows **Update GitHub access** instead of failing later with a raw HTTP 404.
- The required workflow permissions remain Contents write, Workflows write and Pull requests write.
- **Choose my runner** shows the actual local repository-scoped runners from this Beelink.
- The first local runner is selected by default.
- Each runner choice shows its name, Online/Offline state and ForgeCore Node ID.
- **Any ForgeCore runner for this repository** remains available only as a separate fallback.
- Delete selected and per-workflow Delete stay disabled until repository file access is verified.
- Normal runner status remains local-first and does not return to GitHub polling.

The full Beta 29 validation passed on the real self-hosted ForgeCore runner.

Version: 0.1.0-beta.29

Source branch: `clean-beta/workflow-access-v29`

Source commit: `7ddd0f5c9bea18ad687287dbdf58e56e17357f26`
