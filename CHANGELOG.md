# Changelog

All notable changes to this repository are documented here.

## Unreleased

## v0.26.0 - 2026-08-28

### Added

- Milnueve private tracker integration through Prowlarr.
- Tracker-specific 96-hour seeding enforcement through qBittorrent.
- Cleanup protection for explicit per-torrent private tracker seeding limits.
- Automatic recovery of stopped media-stack services with a systemd watchdog.
- Five-minute watchdog scheduling with dynamic Docker Compose service discovery.
- Maintenance locking between watchdog, backup, and restore operations.
- Non-recreating service recovery with post-recovery state verification.
- Automated media-stack configuration backups.
- Zstandard-compressed backup archives with SHA-256 verification.
- Backup retention and regenerable-data exclusions.
- Hardened backup handling for NAS-local secrets.
- Validated media-stack configuration restore.
- Automatic pre-restore safety backups.
- Restore rollback protection.
- Archive path and critical-content validation.
- Restored secret permission hardening.
- Pre-start byte-for-byte restore integrity validation.
- Backup, dry-run backup, restore, and dry-run restore Make targets.
- Automated Seerr configuration.
- Automatic Sonarr integration for TV requests.
- Automatic Radarr integrations for Movies and Kids Movies.
- Automatic `Latino 1080p` profile and root-folder selection.
- Seerr configuration and dry-run Make targets.
- Seerr configuration in the normal deployment workflow.

### Documentation

- Document media-stack runtime recovery behavior and watchdog limitations.
- Document media-stack backup and restore workflows and safety controls.
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
