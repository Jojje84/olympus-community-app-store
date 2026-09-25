# ForgeCore Clean Beta

ForgeCore Clean Beta is the GitHub-first ForgeCore package for Umbrel.

## Beta 9

- Adds a dedicated **CI / Workflows** view.
- Lists workflow files from each connected repository without adding startup delay.
- Shows detected `runs-on` routing and whether an online runner matches those labels.
- Shows the latest GitHub Actions run when the current GitHub App has Actions read permission.
- Workflow **Details** can rename the top-level workflow `name:` by committing the YAML change to the repository default branch.
- New ForgeCore GitHub Apps request **Contents: read/write** and **Actions: read**.
- Existing ForgeCore GitHub Apps created before Beta 9 can still list workflows through repository contents; rename may require granting Contents read/write once in GitHub App permissions.
- Beta 8 fast-login cache and Runner onboarding remain unchanged.

Version: 0.1.0-beta.9

Source branch: `clean-beta/workflows-ui-v9`
Source commit: `b6ce0e9bf7c63a36d7051698037f01efd29da105`
