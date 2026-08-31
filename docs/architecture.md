# Architecture

## Overview

The homelab uses a local-development and remote-deployment model.

Configuration, automation, and tests are maintained in Git on the
development workstation. The UGREEN NAS is treated as the production
deployment target.

## Host

The primary host is a UGREEN NAS with:

- Debian 12
- ARM64 architecture
- Docker Engine
- Docker Compose
- persistent storage under `/volume1`

## Deployment Model

Production services are managed with Docker Compose.

The normal workflow is:

1. modify configuration locally
2. validate and test locally
3. upload configuration and automation scripts over SSH
4. validate the deployment on the NAS
5. pull container images
6. apply the Compose stack
7. configure applications through their APIs
8. synchronize managed policies

This keeps application configuration reproducible and minimizes manual
changes through service web interfaces.

## Media Services

| Service | Role |
| --- | --- |
| Prowlarr | Indexer management |
| Sonarr | TV automation |
| Radarr | Movie automation |
| Bazarr | Subtitle automation |
| Seerr | Media requests |
| qBittorrent | Download client |
| Jellyfin | Media playback and library management |
| FlareSolverr | Cloudflare-compatible proxy support |
| Recyclarr | TRaSH Guides synchronization |

All media services are managed through Docker Compose.

## Storage

Primary storage paths:

```text
/volume1/Family/Downloads
/volume1/Family/Media
```

The deployed stack is stored under:

```text
/volume1/docker/media-stack
```

Application configuration is stored under:

```text
/volume1/docker/media-stack/config
```

Runtime automation is installed under:

```text
/volume1/docker/media-stack/scripts
```

## Secrets

Runtime secrets are not stored in Git.

NAS-local secrets are stored under:

```text
/volume1/docker/media-stack/secrets
```

Private Prowlarr credentials, when configured, are loaded from:

```text
/volume1/docker/media-stack/secrets/prowlarr-private-indexers.json
```

This file currently supports Milnueve and RetroToon World credentials.
RetroToon uses Generic Torznab and receives a per-torrent 72-hour seeding
limit through Prowlarr. Credentials and passkeys remain NAS-local.

Only safe example files are version controlled.

## Configuration Automation

The repository configures applications through scripts and service APIs.

Managed areas include:

- Prowlarr indexers
- qBittorrent categories and preferences
- Sonarr and Radarr download clients
- Sonarr and Radarr root folders
- naming and media-management settings
- custom formats and profile scores
- Recyclarr synchronization
- Latino release policies
- release auditing and upgrades
- completed-download cleanup
- dangerous-download remediation

Configuration scripts are designed to be idempotent whenever practical.

## Future Stacks

The repository also reserves stack directories for:

- AI
- monitoring
- networking
- security

These stacks are not yet production workloads.
