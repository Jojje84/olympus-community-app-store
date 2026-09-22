# GitHub CI Runner for Olympus

A GitHub Actions self-hosted runner designed for a dedicated Beelink/Umbrel build server.

## Architecture

- Official GitHub Actions runner image
- Dedicated Docker-in-Docker daemon
- No mount of Umbrel's host `/var/run/docker.sock`
- Persistent Docker, Go, npm and Playwright caches
- Conservative weekly Docker cleanup
- Repository registration token removed after first successful registration

## First setup

1. Install **GitHub CI Runner** from the Olympus App Store.
2. In the target GitHub repository open **Settings → Actions → Runners → New self-hosted runner**.
3. Copy the short-lived registration token.
4. SSH into Umbrel and run:

   ```bash
   bash ~/umbrel/app-data/olympus-github-ci-runner/data/configure.sh
   ```

5. Enter the repository URL, runner name, labels and registration token.
6. Restart the Umbrel app.

For UniCore use labels:

```text
beelink,unicore-build
```

Then jobs can target:

```yaml
runs-on: [self-hosted, Linux, X64, beelink, unicore-build]
```

## Multiple projects

GitHub repository-level runners belong to one repository. If repositories are owned by a personal GitHub account, use a separate runner instance for each repository while keeping the same CI base and labels.

If projects are moved into a GitHub Organization later, an organization-level runner can be shared across selected repositories.

## Security

The CI daemon is intentionally separate from Umbrel's host Docker socket. The Docker-in-Docker service is still privileged, so only trusted repositories and trusted workflow changes should be allowed to execute on it. Do not run untrusted fork PR code on this runner.
