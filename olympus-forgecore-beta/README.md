# ForgeCore Clean Beta

ForgeCore Clean Beta is the GitHub-first ForgeCore package for Umbrel.

## Beta 17

Beta 17 is the runner-backed workflow hardening release. It keeps Beta 16 protected-branch handling, pull-request fallback and workflow auto-refresh, while making workflow mutations observable and adding a live release gate.

- Workflow rename and delete show inline progress and final status instead of looking stuck.
- GitHub workflow mutations use a bounded 90-second timeout.
- Successful workflow writes no longer wait for a full repository/status refresh before the result is shown.
- The release gate now performs a real GitHub workflow create, rename and delete through the installed ForgeCore authentication on a self-hosted ForgeCore runner.
- Shell, JavaScript, Python, Compose and clean runner-boundary validation are all part of the same gate.
- The final publication candidate was revalidated after correcting the Beta 17 release metadata.

Version: 0.1.0-beta.17

Source branch: `clean-beta/workflow-ops-v17-preflight`

Source commit: `cb3020767c01e606131b5dde9b4d46b768a0ffcb`
