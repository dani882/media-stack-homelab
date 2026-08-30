# Media Stack

The media stack provides automated media discovery, download management,
library organization, subtitle management, and playback.

It is deployed to the UGREEN NAS through Docker Compose.

## Services

| Service | Purpose | Deployment |
| --- | --- | --- |
| Prowlarr | Indexer management | Docker Compose |
| Sonarr | TV automation | Docker Compose |
| Radarr | Movie automation | Docker Compose |
| Bazarr | Subtitle automation | Docker Compose |
| Seerr | Media requests | Docker Compose |
| qBittorrent | Torrent client | Docker Compose |
| Jellyfin | Media server | Docker Compose |
| FlareSolverr | Cloudflare-compatible proxy support | Docker Compose |
| Recyclarr | TRaSH Guides synchronization | Docker Compose |

## Storage

Primary NAS paths:

```text
/volume1/Family/Downloads
/volume1/Family/Media
/volume1/docker/media-stack
```

Container configuration is deployed under:

```text
/volume1/docker/media-stack/config
```

Runtime scripts are installed under:

```text
/volume1/docker/media-stack/scripts
```

Runtime secrets are stored under:

```text
/volume1/docker/media-stack/secrets
```

## Prowlarr

Prowlarr indexers are configured automatically by:

```text
scripts/configure-prowlarr.py
```

Managed public indexers currently include:

- 1337x
- Knaben
- LimeTorrents
- Torrent Downloads
- The Pirate Bay
- EZTV

Configuration is idempotent.

Run manually with:

```bash
make configure-prowlarr
```

Preview changes with:

```bash
make dry-run-prowlarr
```

## Optional Private Indexers

The stack supports optional private Prowlarr indexers.

Milnueve is currently the first production private tracker integrated with
the stack. Its API credential remains NAS-local and is loaded from the
private indexer secret file.

Managed Milnueve policy includes:

- Prowlarr priority `4`
- minimum seeders `1`
- 96-hour (`5760` minute) per-torrent seeding requirement
- automatic propagation through Prowlarr to Sonarr and Radarr
- qBittorrent per-torrent seeding limits
- cleanup protection that honors tracker-provided seeding limits

Supported templates currently include:

- Lat-Team
- ChileBT
- BTArg

Example configuration:

```text
stacks/media/secrets/prowlarr-private-indexers.example.json
```

The real secret file is NAS-local:

```text
/volume1/docker/media-stack/secrets/prowlarr-private-indexers.json
```

Real credentials must never be committed.

## qBittorrent

qBittorrent configuration is automated.

Managed categories include:

```text
movies -> /data/Downloads/complete/movies
tv     -> /data/Downloads/complete/tv
```

Radarr uses the separate `radarr` category. Its qBittorrent category
save path is intentionally empty, so Automatic Torrent Management
resolves new downloads beneath the default path as
`/data/Downloads/radarr`.

Run manually with:

```bash
make configure-qbittorrent
```

## Sonarr and Radarr

Sonarr and Radarr are configured through shared Servarr modules.

Managed configuration includes:

- download clients
- root folders
- naming
- media management
- custom formats
- profile scores

Run manually with:

```bash
make configure-servarr
```

## Seerr

Seerr provides the request-management layer for the media stack.

Users can search for movies and TV series through Seerr and submit requests.
Seerr routes TV requests to Sonarr and movie requests to Radarr. Sonarr and
Radarr then handle release selection, downloading, and library management.

The repository automatically configures Seerr with:

- Jellyfin as the media server
- Sonarr for TV requests
- Radarr Movies for normal movie requests
- Radarr Kids Movies for kids movie requests
- the `Latino 1080p` quality profile
- the appropriate Sonarr and Radarr root folders
- automatic Seerr initialization

Run the managed configuration with `make configure-seerr`.

Preview the configuration without applying changes with
`make dry-run-seerr`.

The Sonarr and Radarr configuration is reconciled idempotently.

Jellyfin library selection is also attempted automatically. The current
Seerr behavior accepts the library enable request but does not persist the
enabled state. The automation detects this condition, reports a warning,
and allows the rest of the configuration and deployment to continue.

## Latino Release Policy

The media stack prefers Spanish Latino releases while allowing English
fallback releases when Latino media is not yet available.

Custom formats include:

- `[Latino] Spanish Latino`
- `[Latino] Spanish Latino + English`
- `[Latino] French Bonus`
- `[Audio] Audio Description`

Current scores:

```text
[Latino] Spanish Latino             7000
[Latino] Spanish Latino + English   7000
[Latino] French Bonus                250
[Audio] Audio Description         -10000
```

This allows the stack to:

1. download an acceptable fallback release
2. continue monitoring for a better Latino release
3. replace the fallback when a suitable Latino upgrade becomes available

## Sonarr Latino Audit and Upgrades

Audit available Latino releases:

```bash
make audit-latino SERIES="Silo" SEASON=3
```

Preview upgrades:

```bash
make dry-run-upgrade-latino SERIES="Silo" SEASON=3
```

Apply upgrades:

```bash
make upgrade-latino SERIES="Silo" SEASON=3
```

## Radarr Latino Audit and Upgrades

Audit a movie:

```bash
make audit-radarr-latino MOVIE_ID=2
```

Preview an upgrade:

```bash
make dry-run-upgrade-radarr-latino MOVIE_ID=2
```

Apply an upgrade:

```bash
make upgrade-radarr-latino MOVIE_ID=2
```

## Audio Description Protection

Releases that explicitly advertise Audio Description are matched by the
`[Audio] Audio Description` custom format.

They receive a score of `-10000`, preventing them from being selected as
normal fallback media.

## Dangerous Download Protection

Sonarr and Radarr may detect dangerous payloads such as unexpected
executable files.

The shared cleanup logic recognizes warnings such as:

```text
Found potentially dangerous file with extension
```

Dangerous completed downloads are:

1. detected from the Arr queue
2. removed from qBittorrent
3. deleted from disk
4. removed from the Arr queue
5. blocklisted
6. allowed to be searched again using another release

Dangerous downloads may bypass the normal local seeding wait, but explicit
per-torrent seeding limits supplied by private trackers are always honored.

## Download Cleanup

Normal stale completed downloads are cleaned only when safety checks pass.

Checks include:

- expected qBittorrent category
- completed download state
- zero bytes remaining
- Force Start disabled
- safe torrent state
- minimum seeding period

Preview:

```bash
make dry-run-cleanup-sonarr-downloads
make dry-run-cleanup-radarr-downloads
```

Apply:

```bash
make cleanup-sonarr-downloads
make cleanup-radarr-downloads
```

## Backup and Restore

The media stack supports automated configuration backups and validated
restores.

Backups include persistent application configuration and state for:

- Prowlarr
- Sonarr
- Radarr
- Bazarr
- Seerr
- qBittorrent
- Jellyfin configuration and metadata
- Recyclarr state and configuration
- NAS-local media-stack secrets

Regenerable data such as logs, caches, application-generated backups,
Sonarr/Radarr MediaCover, Recyclarr resources, Jellyfin cache, and generated
keyframes is excluded.

Backups are compressed with Zstandard and accompanied by a SHA-256 checksum.
Backup archives and checksum files use restrictive permissions. NAS-local
secret files are normalized to `0600 root:root`.

Preview a backup with:

```bash
make dry-run-backup
```

Create a backup with:

```bash
make backup
```

The default backup retention period is 14 days.

Preview a restore with:

```bash
make dry-run-restore \
  BACKUP=/volume1/docker/media-stack/backups/media-stack-YYYYMMDDTHHMMSSZ.tar.zst
```

Run a live restore with:

```bash
make restore \
  BACKUP=/volume1/docker/media-stack/backups/media-stack-YYYYMMDDTHHMMSSZ.tar.zst
```

Restore safety controls include:

- SHA-256 checksum verification
- rejection of unsafe archive paths
- critical-file validation
- preservation of numeric UID/GID ownership
- automatic pre-restore safety backup
- rollback storage for replaced live configuration
- automatic rollback when restore fails
- restored secret permission hardening
- byte-for-byte integrity validation before service startup
- restarting only services that were running before the restore

## Recyclarr

Recyclarr synchronizes TRaSH Guides configuration with Sonarr and Radarr.

Run manually with:

```bash
make sync-recyclarr
```

Custom local formats are preserved through configured exclusion patterns.

## Deployment

Deploy the full stack:

```bash
make deploy
```

The deployment workflow:

1. validates local configuration
2. uploads configuration and scripts
3. installs files on the NAS
4. validates Compose configuration
5. pulls images
6. applies containers
7. configures Prowlarr
8. configures qBittorrent
9. configures Sonarr and Radarr
10. synchronizes Recyclarr
11. reapplies Radarr-specific post-Recyclarr policy

## Testing

Run all tests:

```bash
make test
```

Run the full repository validation:

```bash
make check
```

Current automated tests cover:

- Latino release detection
- Latino release ranking
- dangerous download warning detection
- cleanup safety logic
- private Prowlarr indexer loading

## Operational Safety

Prefer the dry-run target first for destructive operations when one exists.
