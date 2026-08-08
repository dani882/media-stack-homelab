# ADR-0001: Use Docker Compose for Service Deployment

## Status

Accepted

## Context

The UGREEN App Center provides a convenient installation mechanism but does
not provide the reproducibility, portability, and version control required
for an Infrastructure as Code workflow.

The homelab requires service definitions and deployment configuration that
can be reviewed, tested, backed up, and recreated from Git.

## Decision

Docker Compose is the standard deployment mechanism for homelab services.

Application configuration should also be automated through configuration
files, service APIs, or repository-managed scripts whenever practical.

The NAS is treated as a deployment target rather than the primary location
where configuration is authored.

## Consequences

Benefits include:

- version-controlled infrastructure
- repeatable deployments
- easier disaster recovery
- portable service definitions
- automated validation
- reduced dependence on manual web-interface configuration

The approach also requires maintaining:

- Compose definitions
- deployment automation
- persistent configuration paths
- secret-handling conventions
- application configuration scripts
- automated tests

The production media stack has been migrated to Docker Compose, including
Jellyfin and qBittorrent.

Future homelab services should use the same deployment model unless a later
ADR documents an exception.
