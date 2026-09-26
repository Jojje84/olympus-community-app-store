# ForgeCore Runner Core Beta

ForgeCore is a local-first self-hosted GitHub Actions runner manager for Umbrel.

## Beta 26

Beta 26 connects runner creation and workflow routing into one operation.

- **Add runner** loads the real GitHub Actions workflows from the selected repository.
- Select existing workflows while creating the runner.
- Optionally create missing **Build**, **Test**, **Release** and **Deploy** starter workflows in the same flow.
- ForgeCore registers the runner first, waits until GitHub sees it, adds the runner's stable `fc-route-*` label and then updates the selected workflow files automatically.
- Workflow assignment is persisted locally and retried in the background, so closing the browser does not cancel the operation.
- Runner cards show whether workflow setup is connecting, retrying or complete.
- Manual workflow assignment remains available later for changes.
- Runner identity remains tied to this ForgeCore node via the persistent `fc-node-*` label.
- Normal runner status remains local-first on the Beelink.

GitHub still chooses self-hosted runners through each workflow's `runs-on` value. ForgeCore now manages that automatically when the runner is created.

Version: 0.1.0-beta.26

Source branch: `clean-beta/auto-workflow-bind-v26`

Source commit: `7688b5c1cad0aba7069eae016a162836593e10f0`
