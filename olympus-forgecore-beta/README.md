# ForgeCore Clean Beta

ForgeCore Clean Beta is the GitHub-first ForgeCore package for Umbrel.

## Beta 12

- Fixes GitHub workflow edits that appeared available in ForgeCore but were not allowed by the connected GitHub App.
- New ForgeCore GitHub Apps now request **Contents: Read & write** and **Workflows: Read & write**.
- Existing installations show whether workflow editing permission is ready or still needs approval.
- Workflow Details shows a clear permission warning when GitHub will block rename, routing or delete.
- Rename only reports success after GitHub confirms the commit and ForgeCore verifies the new workflow name on the target branch.
- Runner Routing and Delete workflow now return the same actionable permission guidance.
- Keeps all Beta 11 Runner Routing and Beta 10 runner lifecycle/self-healing features.

Version: 0.1.0-beta.12

Source branch: `clean-beta/workflow-write-permission-v12`
