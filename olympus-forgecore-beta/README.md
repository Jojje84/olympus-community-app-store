# ForgeCore Runner Core Beta

ForgeCore Runner Core is the focused self-hosted GitHub Actions runner manager for Umbrel.

## Beta 23

Beta 23 makes workflow assignment a first-class runner setting and removes the need to refresh after accepted runner changes.

- Create runner now offers **Build workflow**, **Test workflow**, **Release workflow** and **Deploy workflow** assignments.
- ForgeCore maps those assignments to GitHub self-hosted runner labels.
- Runner cards show the active workflow assignments directly.
- Edit runner can change name, workflow assignments and custom labels.
- Accepted edits are reflected immediately while the runner reconnects.
- Accepted removals disappear immediately from the dashboard while GitHub/local cleanup finishes.
- Pending operations are protected from periodic refresh so stale state does not flash back into the UI.
- The release validation now runs all checks as steps inside one self-hosted job, avoiding repeated runner reservation between test jobs.

GitHub workflow routing still uses `runs-on` labels under the hood. Example:
- Build: `runs-on: [self-hosted, ForgeCore, build]`
- Release: `runs-on: [self-hosted, ForgeCore, release]`

Version: 0.1.0-beta.23

Source branch: `clean-beta/workflow-assignments-v23`

Source commit: `287c884b17543bceb0a88ed3909a0452dbed4a7b`
