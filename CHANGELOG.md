# Changelog

All notable changes to this repository are documented here.

## Unreleased

### Documentation

- Refresh project documentation to reflect the current architecture,
  deployment model, media automation, security protections, and roadmap.

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
