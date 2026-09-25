# ForgeCore Clean Beta

ForgeCore Clean Beta is the GitHub-first ForgeCore package for Umbrel.

## Beta 18

Beta 18 fixes stale GitHub App permission handling for workflow edits.

- ForgeCore now treats Contents write, Workflows write and Pull requests write as the complete permission set required by the default-branch workflow editor.
- Rename, runner routing and delete are disabled before any GitHub write when the installed app is missing one of those permissions.
- The workflow dialog shows a direct **Repair GitHub integration** action and **Recheck permissions** instead of letting the operation fall through to a raw GitHub 403.
- The server enforces the same permission gate on the workflow editing API.
- Low-level workflow mutation functions still work on ordinary non-default branches, so the live GitHub create/rename/delete release test remains meaningful.
- The full release gate passed on the ForgeCore self-hosted runner: shell, JavaScript, Python, Compose, runner-boundary and live GitHub workflow mutations.

Version: 0.1.0-beta.18

Source branch: `clean-beta/permission-gate-v18`

Source commit: `b4e8918787fc174cf51756a28a0421a534b6bf15`
