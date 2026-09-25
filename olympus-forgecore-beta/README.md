# ForgeCore Clean Beta

ForgeCore Clean Beta is the GitHub-first ForgeCore package for Umbrel.

## Beta 16

Beta 16 fixes the two concrete problems found after Beta 15: workflow mutations were still being sent directly to a protected default branch, and the Workflows screen had no automatic refresh loop.

- **Protected branches are supported.** Rename, routing and delete first try the selected branch directly. If GitHub repository rules require a pull request, ForgeCore automatically creates a temporary `forgecore/...` branch, applies the change there and opens a pull request to the protected branch.
- The GitHub App now requests **Pull requests: Read & write** in addition to Contents write, Workflows write, Actions read, Administration write and Metadata read.
- Workflow rename is verified by re-reading the requested display name from the branch where the change was committed.
- Runner routing is verified by re-reading every changed job's `runs-on` value.
- Workflow delete is verified by confirming the file is absent from the change branch.
- The UI clearly distinguishes **Applied** from **Waiting for merge** and links directly to the generated pull request.
- If a rename is waiting on a pull request, ForgeCore explicitly keeps showing the old default-branch name and explains why.
- The Workflows screen now auto-refreshes every **10 seconds** while it is open, in addition to the manual Refresh button.
- Keeps Beta 15 GitHub capability diagnostics/repair flow and Beta 13–14 multi-runner, per-job routing, hosted-minute and queue diagnostics.

Version: 0.1.0-beta.16

Source branch: `clean-beta/protected-workflows-v16`
