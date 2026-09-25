# ForgeCore Clean Beta

ForgeCore Clean Beta is the GitHub-first ForgeCore package for Umbrel.

## Beta 14

- Workflow permission status now has three honest states: **Ready**, **Approval required**, and **Could not verify**.
- Unknown permission status no longer blocks workflow changes. Rename, routing and delete are attempted against GitHub and ForgeCore reports the real GitHub response.
- Successful workflow writes are recorded with time, repository, operation and commit so Account can show the last verified write.
- Workflow Details now show a **routing summary** for every job.
- Private-repository jobs routed to GitHub-hosted runners are marked as using GitHub-hosted Actions minutes; ForgeCore/self-hosted jobs are marked as not using hosted-runner minutes.
- Workflow Details and Repository Details include **queue / runner capacity** diagnostics, including busy, offline and label-mismatch reasons for queued self-hosted jobs.
- Workflow rename is explicitly a **display name** change; the YAML filename is shown separately.
- Workflow delete now shows repository, branch and file and requires typing `DELETE`.
- Keeps Beta 13 multiple runners per repository and per-job routing to GitHub Ubuntu/Windows/macOS, any ForgeCore runner, or one specific runner.

Version: 0.1.0-beta.14

Source branch: `clean-beta/permissions-diagnostics-v14`
