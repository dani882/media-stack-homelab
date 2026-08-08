# Changelog

All notable changes to this repository are documented here.

## Unreleased

### Added

- Automated Seerr configuration.
- Automatic Sonarr integration for TV requests.
- Automatic Radarr integrations for Movies and Kids Movies.
- Automatic `Latino 1080p` profile and root-folder selection.
- Seerr configuration and dry-run Make targets.
- Seerr configuration in the normal deployment workflow.

### Documentation

- Document Seerr request-management integration and automation.
- Refresh project documentation to reflect the current architecture,
  deployment model, media automation, security protections, and roadmap.

### Known Issues

- Seerr currently accepts Jellyfin library enable requests but does not
  persist the enabled library state. The automation detects and reports
  this condition without failing deployment.

## v0.24.0

### Added

- Optional private Prowlarr indexer support.
- NAS-local private indexer credential loading.
- Private indexer templates for Lat-Team, ChileBT, and BTArg.
- Example private indexer secrets file.
- Unit tests for private indexer configuration loading.

## v0.23.0

### Added

- Audio Description release rejection.
- Dangerous download warning detection.
- Immediate cleanup of dangerous completed downloads.
- Dangerous release blocklisting.
- Cleanup tests for dangerous download behavior.

## v0.22.0

### Changed

- Refactored media automation into shared Python modules.
- Shared Arr API client infrastructure.
- Shared qBittorrent client infrastructure.
- Shared Sonarr and Radarr cleanup logic.
- Shared Latino release detection and ranking logic.

### Added

- Unit tests for shared Latino release helpers.

## Earlier Milestones

- Migrated Jellyfin from the UGREEN App Center to Docker Compose.
- Migrated qBittorrent from the UGREEN App Center to Docker Compose.
- Added automated Prowlarr, qBittorrent, Sonarr, and Radarr configuration.
- Added Recyclarr synchronization.
- Added Latino release auditing and automated upgrades.
- Added completed-download cleanup automation.
- Added Docker Compose deployment and repository validation.
