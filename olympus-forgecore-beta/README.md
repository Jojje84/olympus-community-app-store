# ForgeCore Clean Beta

ForgeCore Clean Beta is the GitHub-first ForgeCore package for Umbrel.

## Beta 10

- Keeps the Beta 9 CI / Workflows view and workflow routing visibility.
- Adds Start, Stop, Restart, Remove and Diagnostics for ForgeCore-managed runners.
- Restarts managed runners without deleting their GitHub registration or asking for a new token.
- Automatically recovers managed runners after unexpected exits, with restart-loop protection.
- Shows uptime, restart count, last restart, runner ownership and current busy state.
- Adds Needs attention signals for duplicate registrations, inventory errors and managed runner failures.
- Allows stale external GitHub runner registrations to be removed directly after confirmation.
- Keeps external runners visible but does not pretend ForgeCore can start or restart a process on another machine.
- Allows a local ForgeCore Runner to be added even when external runners already exist for the repository.

Version: 0.1.0-beta.10

Source branch: `clean-beta/runner-workflows-v10`
