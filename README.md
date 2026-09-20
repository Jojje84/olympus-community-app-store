# Olympus App Store

A curated Umbrel Community App Store for self-hosted apps.

## Add to Umbrel

Add this repository as a Community App Store in umbrelOS:

`https://github.com/Jojje84/zeus-community-app-store`

## Apps

- **SparkyFitness** — health, nutrition and workout tracking
- **Lyftr** — lightweight workout and nutrition tracking

## Automatic update discovery

Olympus scans **every app package in this repository automatically every day**. There is no hard-coded list of apps in the updater.

For each top-level app folder that contains both `umbrel-app.yml` and `docker-compose.yml`, Olympus:

1. reads the upstream GitHub repository from `repo:` in `umbrel-app.yml`;
2. checks GitHub Releases for a newer version;
3. follows stable releases for stable apps, and prereleases when the currently packaged app is already a prerelease;
4. updates Docker image tags that match the currently packaged app version;
5. opens a pull request for review.

Sidecars such as PostgreSQL and Redis are not touched because their versions do not match the app release version.

Updates are **never auto-merged**. A human review remains required before an update becomes available through the Umbrel store.

### Adding future apps

A newly added app is discovered automatically as long as it has:

- `umbrel-app.yml`
- `docker-compose.yml`
- a GitHub `repo:` URL in the manifest
- versioned application Docker image tags that correspond to its upstream release

No central updater configuration needs to be edited when another app is added.
