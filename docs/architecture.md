# Architecture

## Host

- UGREEN NAS
- Debian 12
- ARM64
- Docker Compose
- Storage mounted under `/volume1`

## Services

- Prowlarr: indexer management
- Sonarr: TV automation
- Radarr: movie automation
- Bazarr: subtitle automation
- Seerr: media requests
- FlareSolverr: Cloudflare-compatible indexer proxy
- Recyclarr: TRaSH Guides synchronization
- Jellyfin: currently managed by UGREEN App Center
- qBittorrent: currently managed by UGREEN App Center

## Storage

- Downloads: `/volume1/Family/Downloads`
- Media: `/volume1/Family/Media`
- Container config: `/volume1/docker/media-stack/config`

## Current migration state

Jellyfin and qBittorrent remain under UGREEN App Center until their data and settings are backed up and tested under Docker Compose.
