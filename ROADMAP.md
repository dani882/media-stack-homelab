# Roadmap

This roadmap tracks major homelab capabilities rather than assigning
speculative version numbers to unfinished work.

## Completed

### Infrastructure

- [x] Establish Infrastructure as Code repository
- [x] Adopt Docker Compose as the deployment model
- [x] Add local validation and automated tests
- [x] Add SSH-based NAS deployment automation
- [x] Add Git pre-commit repository checks

### Media Platform

- [x] Deploy Prowlarr
- [x] Deploy Sonarr
- [x] Deploy Radarr
- [x] Deploy Bazarr
- [x] Deploy Seerr
- [x] Deploy FlareSolverr
- [x] Deploy Recyclarr
- [x] Migrate qBittorrent to Docker Compose
- [x] Migrate Jellyfin to Docker Compose
- [x] Preserve Jellyfin RKMPP hardware acceleration
- [x] Automate Prowlarr configuration
- [x] Automate qBittorrent configuration
- [x] Automate Sonarr and Radarr configuration
- [x] Automate Seerr configuration
- [x] Integrate Seerr with Sonarr and Radarr
- [x] Automate Recyclarr synchronization
- [x] Implement Latino release preferences
- [x] Implement Latino release auditing and upgrades
- [x] Reject Audio Description releases
- [x] Automate stale completed-download cleanup
- [x] Immediately remediate dangerous downloads
- [x] Add optional private Prowlarr indexer support
- [x] Keep private tracker credentials outside Git
- [x] Integrate and validate first production private tracker

## Next

### Media Platform

- [ ] Configure and validate private indexers
- [ ] Expand automated integration testing
- [x] Implement automated media configuration backups
- [x] Implement validated media configuration restore
- [x] Add automatic recovery for stopped media-stack services
- [x] Document disaster-recovery procedures
- [x] Continue reducing manual application configuration

### Monitoring

- [ ] Select the monitoring toolchain
- [ ] Collect host metrics
- [ ] Collect container metrics
- [x] Add service-health monitoring for the media stack
- [ ] Add centralized logging
- [ ] Add dashboards
- [ ] Add alerting

### AI

- [ ] Define the local AI architecture
- [ ] Evaluate local inference workloads
- [ ] Define model-storage strategy
- [ ] Evaluate accelerator and GPU scheduling
- [ ] Add reproducible AI development environments

### Networking

- [ ] Document the current network architecture
- [ ] Define networking automation requirements

### Security

- [ ] Define secrets-management strategy
- [ ] Review service exposure and network boundaries
- [ ] Add security-focused operational documentation

## Long-Term Goals

- reproducible recovery from a clean system
- automated backups with tested restores
- comprehensive observability
- minimal manual service configuration
- documented disaster recovery
- production-ready security practices
