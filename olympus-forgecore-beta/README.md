# ForgeCore Runner Core Beta

ForgeCore Runner Core is the focused self-hosted GitHub Actions runner manager for Umbrel.

## Beta 22

Beta 22 focuses on managed runner editing, reliable removal and stale-listener recovery.

- Runner details now include **Edit runner**.
- Name and runner labels can be changed after creation.
- Common roles are available directly: **build**, **test**, **release** and **deploy**.
- Additional custom labels remain supported.
- The shared **ForgeCore** label is always preserved automatically.
- Internal ForgeCore route labels are preserved during edits.
- Editing uses one controlled re-registration path rather than the previous reset/register race.
- **Remove runner** deletes the GitHub runner registration first, then cleans up the local ForgeCore runner.
- Busy runners return a clear conflict and can be **Force removed** when a job is genuinely stuck.
- The watchdog now recovers runners that remain locally connecting/offline while GitHub cannot assign new jobs.

Release testing also reproduced the Beta 21 stale-listener case. The edit/remove contract and UI/package checks ran successfully on the self-hosted ForgeCore runner before that installed Beta 21 listener stopped accepting new jobs. The Beta 22 watchdog closes that recovery gap. A direct source/package audit passed all version, contract and Base64 integrity checks before publication.

Version: 0.1.0-beta.22

Source branch: `clean-beta/runner-edit-v22`

Source commit: `627e79ef5674755c5391a79a2460b17151e846f3`
