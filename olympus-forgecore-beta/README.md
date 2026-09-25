# ForgeCore Clean Beta

ForgeCore Clean Beta is the GitHub-first ForgeCore package for Umbrel.

## Beta 19

Beta 19 simplifies normal CI around Runner-only execution.

- GitHub-hosted Ubuntu, Windows and macOS routing choices are removed from the normal workflow editor.
- The routing API rejects attempts to move jobs back to GitHub-hosted compute.
- Existing hosted jobs are detected and can be moved to ForgeCore with **Move all jobs to ForgeCore**.
- Repositories without a managed runner get a **Create ForgeCore runner** action first.
- GitHub Actions may remain as trigger/scheduler, but build and test jobs execute on ForgeCore self-hosted runners.
- Runner health now includes a guarded remote-status watchdog that can request a safe restart when the local process looks online but GitHub reports it offline or missing.
- Release validation no longer depends on live edits to `.github/workflows`. Runner-only routing is tested deterministically, while the self-hosted runner performs a real GitHub branch + file write/read/delete test.
- The complete Beta 19 release candidate passed shell, JavaScript, Python, Compose, runner-boundary and live GitHub repository validation on the ForgeCore runner.

Version: 0.1.0-beta.19

Source branch: `clean-beta/runner-only-v19`

Source commit: `0873f7a4993bcce776925e4addafa12559250862`
