# ForgeCore Runner Core Beta

ForgeCore Runner Core is the focused self-hosted GitHub Actions runner manager for Umbrel.

## Beta 20

Beta 20 rebuilds the Clean Beta around runners only.

- Apps, Delivery and workflow editing are removed from the Clean Beta dashboard.
- GitHub permissions are reduced to metadata read, Actions read and Administration write.
- Repositories are the entry point for creating repository-scoped ForgeCore runners.
- Runner status is shown as Online, Busy, Reconnecting, Offline or Stopped.
- Runner controls include Start, Stop, Restart, Rename, Remove and Force recover.
- Queue/capacity visibility and runner/registration logs are built into the dashboard.
- A remote-status watchdog recovers stale runner listeners, including stale offline+busy states.
- Existing Beta 19 runner metadata is preserved.
- The release gate runs seven separate tests in sequence on the real ForgeCore self-hosted runner.

Validation for the published candidate passed:
1. Python + permission contract
2. Dashboard + mobile boundary
3. Runner manager lifecycle boundary
4. HTTP API boot smoke
5. Package + Compose integrity
6. Beta 19 runner persistence
7. Real self-hosted runner E2E

Version: 0.1.0-beta.20

Source branch: `clean-beta/runner-core-v20`

Source commit: `3a264ebc0a6d5bc9239e60c6861f3cb68c33d8fa`
