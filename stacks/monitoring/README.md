# Monitoring Stack

Status: lightweight observability in place, full stack planned.

The homelab now has a lightweight media-stack observability layer through
systemd timers plus repository-managed audits.

Current implemented coverage for the media stack:

- periodic live service reachability checks
- periodic Seerr policy/routing audit
- periodic Bazarr compatibility audit
- periodic hardlink audit
- log output under `/volume1/docker/media-stack/logs`

A fuller monitoring stack is still planned for broader homelab coverage.

Planned areas include:

- host metrics
- container metrics
- service health
- centralized logs
- dashboards
- alerting

The final full monitoring toolchain has not yet been selected.

See the project [roadmap](../../ROADMAP.md).
