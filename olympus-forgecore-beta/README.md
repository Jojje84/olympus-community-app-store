# ForgeCore Runner Core Beta

ForgeCore Runner Core is a local-first self-hosted GitHub Actions runner manager for Umbrel.

## Beta 27

Beta 27 fixes a status bug where a ForgeCore self-hosted runner could successfully accept and run GitHub Actions jobs while the ForgeCore dashboard remained stuck on Connecting or Offline.

- The runner manager now persists the listener log offset for each start.
- Readiness is checked continuously after the initial startup window.
- A late "Listening for Jobs" signal promotes the local runner state to Online within the normal heartbeat loop.
- No runner re-registration is required for this recovery.
- Normal status refresh remains local-first and does not poll GitHub.
- Beta 26 automatic workflow binding remains intact.

The regression gate explicitly simulates delayed listener readiness and verifies that the state changes from Connecting to Online without restarting the runner.

Version: 0.1.0-beta.27

Source branch: `clean-beta/runner-online-v27`

Source commit: `4aed28f0de250a3cc6b9a4376c1d474c1b00ab4e`
