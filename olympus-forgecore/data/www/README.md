# ForgeCore minimal dashboard

This is intentionally a small, dependency-free status page.

The runtime will update `status.json` with live values. The browser polls that file every 10 seconds.

Initial v1 dashboard shows only:

- GitHub runner status
- external storage usage
- isolated Docker runtime status
- cleanup interval

More controls can be added in later ForgeCore versions without changing the core runner architecture.
