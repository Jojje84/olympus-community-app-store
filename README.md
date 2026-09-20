# Olympus App Store

A curated Umbrel Community App Store for self-hosted apps.

## Add to Umbrel

Add this repository as a Community App Store in umbrelOS:

`https://github.com/Jojje84/olympus-community-app-store`

## Categories

### Health & Fitness
- **SparkyFitness** — health, nutrition and workout tracking
- **Lyftr** — lightweight workout and nutrition tracking

### Gaming & Servers
- **Crafty Controller** — manage Minecraft servers from a web dashboard

This Community App Store uses custom category labels so the Umbrel UI groups the apps as **Health & Fitness** and **Gaming & Servers**.

## Automatic update discovery

Olympus scans **every app package in this repository automatically every day**.
There is no hard-coded list of apps in the updater.

Supported upstream release sources:
- GitHub
- GitLab

For each top-level app folder that contains both `umbrel-app.yml` and
`docker-compose.yml`, Olympus:

1. reads the upstream repository from `repo:` in `umbrel-app.yml`;
2. checks upstream releases for a newer version;
3. updates Docker image tags that match the currently packaged app version;
4. validates the generated Olympus package state;
5. opens an automated pull request;
6. automatically merges the pull request only after the generated state passes validation.

Sidecars such as PostgreSQL and Redis are not touched because their versions do not
match the app release version.

Automatic publishing updates the Olympus repository only. Umbrel still leaves the
actual app installation/update under the user's control.

### Adding future apps

A newly added app is discovered automatically as long as it has:

- `umbrel-app.yml`
- `docker-compose.yml`
- a supported GitHub or GitLab `repo:` URL
- versioned application Docker image tags that correspond to its upstream release

No central updater configuration needs to be edited when another app is added.

## Store validation

Every push and pull request is validated automatically. Olympus checks:

- valid YAML and required manifest fields;
- the required `olympus-` app ID prefix and matching folder names;
- unique, valid Umbrel app ports;
- explicit Docker image tags instead of `:latest`;
- matching `upstream-release.txt` and manifest versions;
- generated Olympus secrets referenced by Compose are provided by `exports.sh`;
- Python script syntax and whitespace errors.

The upstream updater uses GitHub's workflow token for authenticated GitHub API
requests and the third-party GitHub Actions used by the workflows are pinned to
specific commit SHAs.
