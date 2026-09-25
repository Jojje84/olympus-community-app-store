# ForgeCore Clean Beta

ForgeCore Clean Beta is the GitHub-first ForgeCore package for Umbrel.

## Beta 8

- **Add Runner** now asks for a runner name before registration.
- Optional custom labels can be added for GitHub Actions routing; ForgeCore is always included.
- ForgeCore waits for the local listener and GitHub runner inventory to become ready, then shows **Ready for Actions**.
- Managed runner labels are preserved when the runner is renamed.
- After local login, the last dashboard cache is shown immediately before GitHub status is fetched.
- Fresh repositories and runner state still refresh progressively in the background.
- Runtime delivery remains the rendered-artifact model introduced in Beta 7.

Version: 0.1.0-beta.8

Source branch: `clean-beta/runner-onboarding-fast-login-v8`
Source commit: `ec5b6b0f9f67ade4781b4dc2275e2bd33bd13258`
