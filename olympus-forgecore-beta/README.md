# ForgeCore Runner Core Beta

ForgeCore Runner Core is the focused self-hosted GitHub Actions runner manager for Umbrel.

## Beta 21

Beta 21 is a startup hotfix for Runner Core.

Beta 20 rebuilt the dashboard around runners, but the packaged Docker Compose startup guard still searched for the old dashboard marker `Clean Beta · beta.20`. The actual dashboard identifies itself as `Runner Core · beta.20`, so the web container exited immediately during startup.

Beta 21 fixes that mismatch and strengthens the release gate:

- Compose now checks for the real Runner Core dashboard marker.
- The package validation requires Compose, dashboard and server versions to match.
- The validation starts the actual packaged `web` service with `docker compose up` and verifies `/health`.
- The remaining legacy workflow DELETE endpoint is disabled to match the Runner Core boundary.
- The full seven-stage Runner Core validation passed on self-hosted runner ID 24.

Validation passed:
1. Python + permission contract
2. Dashboard + mobile boundary
3. Runner manager lifecycle boundary
4. HTTP API boot smoke
5. Package + Compose integrity, including real packaged web startup
6. Beta 19 runner persistence
7. Real self-hosted runner E2E

Version: 0.1.0-beta.21

Source branch: `clean-beta/runner-core-v21`

Source commit: `3db98c8add8ea5d564066afc76e4796f23e631ce`
