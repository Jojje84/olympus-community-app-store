# ForgeCore Clean Beta

ForgeCore Clean Beta is the GitHub-first ForgeCore package for Umbrel.

## Beta 9

- ForgeCore-managed runners now support **Start**, **Stop**, **Restart**, **Remove** and **Diagnostics**.
- Restart keeps the existing GitHub registration and does not require a new registration token.
- Managed runners automatically recover after unexpected exits, with a restart-loop guard after repeated failures.
- Runner Details shows GitHub identity, labels, status, uptime, restart history and current GitHub Actions job information when available.
- **Needs attention** surfaces likely duplicate registrations, runner failures and GitHub inventory sync problems.
- External runner registrations can be removed from GitHub directly, with busy-runner and ownership safety checks.
- A ForgeCore Runner can be added even when external runners already exist for the same repository.
- External machines remain read/remove-only until they explicitly run a ForgeCore control agent.
- Beta 8 fast-login caching and progressive GitHub refresh behavior are preserved.

Version: 0.1.0-beta.9

Source branch: `clean-beta/runner-operations-v9`
Source commit: `a20911d9d21ed446b0e01e771e02b6dde9db3d41`
