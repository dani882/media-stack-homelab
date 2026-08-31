# Homelab

Infrastructure as Code for a self-hosted homelab running on a UGREEN NAS.

The repository is designed around reproducible, version-controlled
configuration. Development and validation happen locally, while the NAS
is treated as a deployment target.

## Principles

- Infrastructure as Code
- Reproducible deployments
- Git-versioned configuration
- Automated validation and testing
- Minimal manual configuration
- Automated maintenance
- Secure handling of credentials
- Backup and disaster-recovery readiness
- Self-documenting infrastructure

## Current Status

The media stack is the primary production workload and is fully managed
with Docker Compose.

Current release: `v0.28.0`

| Stack | Status |
| --- | --- |
| Media | Active |
| AI | Planned |
| Monitoring | Planned |
| Networking | Planned |
| Security | Planned |

## Media Stack

The current media platform includes:

- Jellyfin
- qBittorrent
- Sonarr
- Radarr
- Prowlarr
- Bazarr
- Seerr
- FlareSolverr
- Recyclarr

The repository also manages application configuration and media policies,
including:

- Prowlarr indexer configuration
- optional private Prowlarr indexers with NAS-only credentials
- Milnueve private tracker integration with 96-hour seeding protection
- qBittorrent categories and preferences
- Sonarr and Radarr download clients and root folders
- Seerr request-management integration with Sonarr and Radarr
- Recyclarr synchronization
- optional Profilarr pilot synchronization
- Spanish-language upgrade policy:
  `Latino > Castellano > English/original`
- audio-description release rejection
- release auditing and upgrade automation
- Sonarr and Radarr download cleanup
- immediate cleanup and blocklisting of dangerous downloads
- automated media configuration backups with retention and checksums
- validated media configuration restore with safety backup and rollback
- automatic recovery of stopped media-stack services through a systemd watchdog
- `/data`-based download and library paths so Sonarr/Radarr imports can use
  hardlinks while qBittorrent continues seeding
- an optional Profilarr pilot for evaluating partial replacement of Recyclarr
  quality-profile management

## Repository Layout

```text
homelab/
|-- docs/               Architecture, ADRs, and operational documentation
|-- scripts/            Deployment, configuration, audit, and maintenance tools
|-- stacks/
|   |-- ai/             Planned AI infrastructure
|   |-- media/          Production media stack
|   |-- monitoring/     Planned observability stack
|   |-- networking/     Planned networking infrastructure
|   `-- security/       Planned security infrastructure
|-- templates/          Configuration templates
|-- tests/              Automated tests
|-- backups/            Backup workspace
|-- Makefile            Development and operational commands
`-- ROADMAP.md          Project roadmap
```

## Deployment Model

All production services are managed with Docker Compose.

The deployment workflow is:

1. Develop and modify configuration locally.
2. Run repository validation and automated tests.
3. Deploy configuration and scripts to the NAS over SSH.
4. Validate the Compose configuration on the NAS.
5. Pull and apply container images.
6. Configure applications through their APIs.
7. Synchronize managed policies and custom formats.

Runtime configuration and secrets remain on the NAS and are not committed
to Git.

### Runtime Recovery

The media stack includes a systemd watchdog timer that checks the desired
Docker Compose service state every five minutes. If one or more expected
services are not running, the watchdog starts the stack with
`docker compose up -d --no-recreate` and verifies that all expected services
are running afterward.

Backup and restore operations coordinate with the watchdog through a shared
maintenance lock so that intentional service stops are not automatically
reversed during maintenance.

The watchdog only recovers Compose services that are not running. It does not
perform application-level health monitoring, and it does not start or modify
the Docker services managed by UGOS.

## Validation

Run the complete repository checks with:

```bash
make check
```

The checks include Compose validation, linting, shell checks, and automated
tests.

## Deployment

Deploy the current configuration with:

```bash
make deploy
```

Individual configuration, auditing, upgrade, and cleanup operations are
also exposed through Make targets. See the `Makefile` for the complete
command list.

## Secrets

Secrets and tracker credentials must never be committed to the repository.

Private Prowlarr indexer credentials are optionally loaded from the NAS:

```text
/volume1/docker/media-stack/secrets/prowlarr-private-indexers.json
```

A safe example is version controlled at:

```text
stacks/media/secrets/prowlarr-private-indexers.example.json
```

Private indexer templates currently exist for:

- Lat-Team API
- ChileBT API
- BTArg

Private indexers are configured only when their credentials are present in
the NAS-side secret file.

## Documentation

Additional documentation:

- [`docs/architecture.md`](docs/architecture.md)
- [`docs/adr/`](docs/adr/)
- [`docs/media-operations.md`](docs/media-operations.md)
- [`stacks/media/README.md`](stacks/media/README.md)
- [`ROADMAP.md`](ROADMAP.md)
- [`CHANGELOG.md`](CHANGELOG.md)

## License

See [`LICENSE`](LICENSE).
