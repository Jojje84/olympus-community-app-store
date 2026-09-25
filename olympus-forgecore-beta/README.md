# ForgeCore Clean Beta

ForgeCore Clean Beta is the GitHub-first ForgeCore package for Umbrel.

## Beta 7

Beta 7 changes how the runtime is delivered to Umbrel. The server, dashboard and runner manager are
shipped as top-level `.b64.template` artifacts. Umbrel renders those artifacts during install/update,
and the containers decode and verify the Beta 7 build before starting. This avoids reusing stale nested
runtime files from an older beta.

User-facing changes:

- Repository **Details** opens repository information instead of navigating to Runners.
- Runner **Details** opens the runner detail panel and management actions.
- Mobile tap handling uses one delegated handler that survives dashboard refreshes.
- The dashboard shows cached data first and progressively refreshes GitHub state in the background.
- Active runtime terminology is Runner-only.

Version: 0.1.0-beta.7

Source branch: `clean-beta/rendered-runtime-v7`
Source commit: `e69314bba4c469cc572b7b036c16a777c12fcd3f`
