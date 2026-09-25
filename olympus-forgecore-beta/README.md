# ForgeCore Clean Beta

ForgeCore Clean Beta is the GitHub-first ForgeCore package for Umbrel.

## Beta 13

- Supports multiple ForgeCore-managed self-hosted runners for the same GitHub repository.
- Keeps workflows structured: one workflow can contain Build, Test, Deploy and other jobs, with a runner choice per job.
- Job routing choices are **GitHub-hosted Ubuntu/Windows/macOS**, **Any ForgeCore runner**, or **Only <specific runner>**.
- Multiple differently named ForgeCore runners are a valid pool and are no longer flagged as duplicates; duplicate detection is reserved for repeated registrations with the same runner name.
- Workflow Details can rename the workflow, change job routing, and delete the workflow file in GitHub.
- When GitHub workflow-write permissions are missing, ForgeCore now links directly to the GitHub App permissions and installation approval pages and can recheck permission state.
- Clean Beta validation itself targets the ForgeCore self-hosted runner pool instead of `ubuntu-latest`, avoiding GitHub-hosted runner minutes for beta validation.
- Keeps Beta 12 workflow write-permission verification and Beta 10–11 runner lifecycle, self-healing and routing behavior.

Version: 0.1.0-beta.13

Source branch: `clean-beta/multi-runner-v13`
