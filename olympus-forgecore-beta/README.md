# ForgeCore Clean Beta

ForgeCore Clean Beta is the GitHub-first ForgeCore package for Umbrel.

## Beta 15

Beta 15 fixes the root cause behind workflow rename, routing, delete and queue/history failures on installations that were originally connected with an older ForgeCore GitHub App.

- Audits the full installed GitHub App permission set: **Contents: write**, **Workflows: write**, **Actions: read**, **Administration: write**, plus metadata read.
- Adds **Repair GitHub integration**. It creates a replacement private ForgeCore GitHub App with the current permission manifest while keeping the old connection active until the replacement install + authorization completes.
- Clearly explains that **All repositories** controls repository selection only; it does not grant API permissions.
- Adds read-only GitHub capability diagnostics for Contents, Actions and self-hosted-runner administration.
- Stops silently turning an Actions 403 into **No recent run**. Workflow history now says when Actions access is unavailable.
- Queue diagnostics no longer show a mystery 403 when Actions permission is missing; the missing capability is explained.
- Workflow rename/routing/delete errors remain visible in the modal with the actual GitHub response and a direct repair action.
- Successful rename/routing changes reload the workflow from GitHub immediately, so the displayed name/routing reflects the committed source.
- Fixes workflow lookup so a refreshed workflow can be reopened by either GitHub workflow ID or workflow file path.
- Requires the local ForgeCore login for runner-job diagnostics.
- Keeps Beta 14 routing summaries, hosted-minute indicators, queue diagnostics and safer workflow deletion, plus Beta 13 multi-runner support.

Version: 0.1.0-beta.15

Source branch: `clean-beta/github-repair-v15`
