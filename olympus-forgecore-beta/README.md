# ForgeCore Beta

ForgeCore is a local-first self-hosted GitHub Actions runner manager for Umbrel.

## Beta 25

Beta 25 fixes the product flow around runners and workflows.

### This ForgeCore
- ForgeCore exposes a persistent Node ID for this Umbrel/Beelink installation.
- New and edited runners receive a machine identity label such as `fc-node-xxxxxxxx`.
- Existing local runners are shown as managed by this ForgeCore and can be **Verify & tag in GitHub** without re-registering.
- Runner health remains local-first through heartbeat and job hooks.

### Runners
- Create, edit, start, stop, restart and remove self-hosted runners from one screen.
- Runner cards explicitly show **This ForgeCore**.
- GitHub identity verification is a manual action, not background polling.

### Real GitHub Workflows
- The Workflows screen now shows the actual files under `.github/workflows` from the selected repository.
- Create, Rename, Assign runner and Delete operate on the real GitHub workflow file.
- Multiple old workflows can be selected and deleted together.
- **Create 4 starters** creates real Build, Test, Release and Deploy workflows.
- Starter workflows use `workflow_dispatch` only, so they do not run automatically until the user edits triggers/commands.
- Assign runner updates workflow `runs-on` to a specific ForgeCore runner.
- Protected branches use the existing pull-request fallback.
- GitHub workflow data is loaded only when the Workflows view is explicitly opened/refreshed.

Workflow editing requires additional GitHub App permissions:
- Contents: Read & write
- Workflows: Read & write
- Pull requests: Read & write

The runner itself continues to work even before those workflow-management permissions are approved.

### Validation
Beta 25 passed one self-hosted validation job with:
1. Node identity + workflow manager contract
2. Dashboard flow + real workflow UX
3. Runner manager local-first lifecycle
4. API boot smoke
5. Package integrity + startup markers
6. Real self-hosted runner E2E

Version: 0.1.0-beta.25

Source branch: `clean-beta/real-workflows-v25`

Source commit: `0ca3035b1c962d8f30726ca87cdc81ecb45a7c1d`
