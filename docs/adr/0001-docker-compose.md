# ADR-0001

## Decision

Docker Compose is the deployment mechanism for all services.

## Status

Accepted

## Context

The UGREEN App Center simplifies installation but does not provide Infrastructure as Code.

Docker Compose enables:

- version control
- repeatable deployments
- backups
- portability

## Consequences

All future services will be deployed using Docker Compose.

Existing App Center services will be migrated gradually.
