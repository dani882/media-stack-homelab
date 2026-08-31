# Homelab Documentation

This directory contains architecture, design decisions, and operational
documentation for the homelab.

## Architecture

See [`architecture.md`](architecture.md) for the current system architecture,
deployment model, storage layout, secrets model, and configuration strategy.

## Architecture Decision Records

Architecture decisions are documented under [`adr/`](adr/).

Current ADRs:

- [`ADR-0001`](adr/0001-docker-compose.md) - Docker Compose as the deployment mechanism

## Stack Documentation

- [`../stacks/media/README.md`](../stacks/media/README.md) - production media stack
- [`../stacks/ai/README.md`](../stacks/ai/README.md) - planned AI stack
- [`../stacks/monitoring/README.md`](../stacks/monitoring/README.md) - planned monitoring stack

## Project Documentation

- [`../README.md`](../README.md) - project overview
- [`../ROADMAP.md`](../ROADMAP.md) - development roadmap
- [`../CHANGELOG.md`](../CHANGELOG.md) - release history
- [`HOMELAB_MEDIA_CONTEXT.md`](HOMELAB_MEDIA_CONTEXT.md) - canonical media
  stack handoff/checkpoint
- [`disaster-recovery.md`](disaster-recovery.md) - media-stack recovery
  checklist
- [`media-legacy-mount-removal.md`](media-legacy-mount-removal.md) - legacy
  mount retirement checklist
- [`media-operations.md`](media-operations.md) - short media-stack
  operations runbook
- [`profilarr-assessment.md`](profilarr-assessment.md) - current Profilarr
  pilot evaluation
