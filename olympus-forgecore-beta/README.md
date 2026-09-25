# ForgeCore Clean Beta

ForgeCore Clean Beta is the GitHub-first ForgeCore package for Umbrel.

## Beta 11

- Keeps the Beta 10 runner operations and CI / Workflows view.
- Adds **Runner Routing** per GitHub Actions job.
- Lets you send **all jobs** in a workflow to GitHub-hosted, any ForgeCore runner, or one specific ForgeCore-managed runner.
- Lets you route only selected jobs to ForgeCore while leaving other jobs unchanged.
- Uses a private ForgeCore routing label when a job must run on one specific managed runner.
- Shows per-job routing health so it is clear whether GitHub has an online matching runner.
- Adds **Delete workflow** in Workflow Details. ForgeCore removes the workflow YAML file from the repository default branch with a Git commit.
- Keeps workflow rename, runner lifecycle controls, self-healing, diagnostics, duplicate cleanup and external runner visibility.

Version: 0.1.0-beta.11

Source branch: `clean-beta/runner-routing-v11`
