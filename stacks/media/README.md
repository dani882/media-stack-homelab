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
| Dispatcharr | IPTV playlist, channel, and EPG management | Docker Compose |
| FlareSolverr | Cloudflare-compatible proxy support | Docker Compose |
| Recyclarr | TRaSH Guides synchronization | Docker Compose |
| Profilarr | Optional quality-profile/custom-format pilot | Docker Compose profile |

## Control Plane Ownership

The stack intentionally uses more than one automation layer.

- repository-managed scripts and JSON files own:
  qBittorrent categories, Sonarr/Radarr settings, Seerr routing, hardlink
  storage layout, cleanup safety logic, and the Spanish-language preference
  policy
- Recyclarr owns:
  TRaSH guide synchronization plus repository-managed exceptions
- Profilarr pilot owns:
  optional generic quality-profile sync for selected Arr instances only

Do not treat Profilarr as the source of truth for:

- `Latino > Castellano > English/original`
- shared-Radarr multi-target routing
- qBittorrent category naming and save-path policy
- private-tracker cleanup protection
- Seerr routing

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

Milnueve, RetroToon World, and Torrent Haven are production private trackers integrated with
the stack. Their credentials remain NAS-local and are loaded from the private
indexer secret file.

All managed private-indexer priorities are numerically ahead of every public
indexer (lower is preferred by Sonarr/Radarr). This prioritizes a private
release when otherwise acceptable results tie, while the existing
`Latino > Castellano > English/original` quality and language policy remains
the primary selection guardrail. A regression test prevents public indexers
from being moved ahead of private ones accidentally.

Managed Milnueve policy includes:

- Prowlarr priority `4`
- minimum seeders `1`
- 96-hour (`5760` minute) per-torrent seeding requirement
- automatic propagation through Prowlarr to Sonarr and Radarr
- qBittorrent per-torrent seeding limits
- cleanup protection that honors tracker-provided seeding limits

Both private trackers are additionally covered by the periodic
private-tracker audit. It checks qBittorrent's reported tracker host and
seeding-time limit without logging announce URLs or passkeys, and treats any
unknown private tracker as an alert until it has an explicit policy.

RetroToon World is supported as an optional Generic Torznab indexer. Its
passkey is an API credential and must remain NAS-local. Its managed policy
uses priority `8`, at least one seeder, and a 72-hour (`4320` minute)
per-torrent seed time. RetroToon also requires that the 72 hours be reached
within ten days of a completed download; the periodic private-tracker audit
alerts when the remaining seed time cannot fit in that window. Prowlarr
discovers RetroToon's Torznab categories and
maps them to standard Sonarr/Radarr categories. Initially the intended scope
is cartoons/anime and animated movies; ambiguous CGI and short-form content
is intentionally not targeted by automation.

Torrent Haven uses Prowlarr's native `torrenthaven-api` definition. Its API
token is generated in Torrent Haven's **My Settings → API Key** page and must
be kept only in the NAS-local private-indexer secret. The managed policy uses
priority `9`, at least one seeder, and a conservative 72-hour (`4320` minute)
seed time for both torrents and packs. Although its rules also accept a 1:1
ratio, the stack does not use ratio as an early-stop condition. Torrent Haven
private torrents are covered by the same private-tracker audit. Its rules also
prohibit DHT, PEX, and additional tracker URLs; qBittorrent currently leaves
discovery enabled globally for public torrents, so do not change those global
settings. A real Torrent Haven torrent has been verified `private=true` with
only `torrenthaven.org` announced, which is the per-torrent behavior required
by the tracker.

If a known private release is missing from Sonarr/Radarr because its metadata
does not resolve through the normal TVDB/TMDB search, retain the Seerr request
and use the guarded `make grab-prowlarr-release` helper. It accepts only an
exact Prowlarr result, validates TVDB for TV or TMDB for movies, uses the
standard qBittorrent category, and enforces the private tracker seed-time
policy without printing its download URL. For movies, set
`MEDIA_TYPE=movie`, `TMDB_ID=...`, and `CATEGORY=radarr`; TV remains the
default and requires `TVDB_ID=...`.

The release title is not a quality guarantee. Radarr/Sonarr imports classify
the actual media with MediaInfo; for example, a Torrent Haven release labeled
`1080p` was detected as 960x540 and retained as `WEBDL-480p`. Confirm the
imported quality and audio languages before treating a release as a preferred
replacement.

### Private-first request policy

`stacks/media/private-release-policy.json` makes the operational policy
explicit. Private candidates are considered before public candidates only when
they meet the language policy and identity checks; it never replaces the
existing `Latino > Castellano > English/original` rule with tracker priority
alone. The guarded helper therefore defaults to Castilian-or-Latino and a
720p title claim. An English/original private release can still be retained
for its required seeding time, but needs an explicit
`MINIMUM_LANGUAGE=english` override and is treated as a fallback to review,
not an automatic preferred replacement.

The health audit runs every 30 minutes and records per-tracker torrent count,
uploaded bytes, downloaded bytes, seeding status, and any compliance risk in
`logs/media-observability.log`. This is also the scheduled evidence for the
24–48 hour Torrent Haven check; account-side statistics must be compared in
Torrent Haven's web UI because its API integration does not expose a stable
account-statistics endpoint.

### Scheduled private-request dispatcher

`media-stack-private-dispatch.timer` evaluates outstanding Seerr movie
requests every 30 minutes. It is deliberately **preview-only**: it requires an
exact TMDB match, one or more seeders, and the repository's Castilian-or-Latino
plus 720p private-release policy. Its output is retained in the system journal;
it neither downloads nor changes a request by itself.

Use `make dispatch-private-seerr` to run the same evaluation on demand. The
explicit `APPLY=1 make dispatch-private-seerr` path is idempotent: it refuses a
request that already has a `seerr-request-<id>` qBittorrent tag. Enable
automatic grabs only after a live candidate has passed that apply path and the
Arr import/hardlink result has been verified.

For an already completed, non-standard RetroToon TV pack, use the title-matched
import helper. It previews by default and creates only hardlinks whose English
episode title has exactly one Sonarr match; ambiguous, multi-episode, and
localized-only filenames are left untouched for review.

```bash
make dry-run-import-sonarr-title-matched \
  SERIES_ID=31 \
  SOURCE="/volume1/Family/Downloads/complete/tv/Las Supernenas (1992)"
```

After reviewing the preview, replace `dry-run-` with `import-`. The helper
rescans the series after it creates links and never removes the download, so
the private torrent remains seedable.

Supported templates currently include:

- Milnueve API
- RetroToon World (Generic Torznab)
- Torrent Haven (native API)
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

Download queueing remains capped at three active downloads, but torrents below
2 KiB/s for 60 seconds do not consume a slot. This lets stalled torrents wait
for peers without blocking a healthy download; it avoids using Force Start.

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

Servarr root folders are declarative. The managed configuration removes root
folder entries not present in `servarr/*/root-folders.json` after Servarr has
migrated all library records. This keeps obsolete `/media/...` destinations
out of Seerr while retaining the Docker compatibility mounts themselves.

Run the managed configuration with `make configure-seerr`.

Preview the configuration without applying changes with
`make dry-run-seerr`.

The Sonarr and Radarr configuration is reconciled idempotently.

Jellyfin library selection is also configured automatically. The managed
script now uses the safe Jellyfin settings endpoint for reads and only uses
the mutating library endpoint for the actual apply step, so the enabled
library state persists correctly.

### Browser-facing Jellyfin links

Seerr keeps `jellyfin:8096` as its Docker-internal connection. During each
configuration run it discovers the NAS hostname and Jellyfin's published Docker
port, then manages a browser-facing mDNS URL such as
`http://dh4300plus-9186.local:8899`. `Play on Jellyfin` links therefore avoid
both Docker-only hostnames and hard-coded IP addresses. `make audit-seerr`
verifies the discovered external URL as well as the media libraries.

## Dominican Republic IPTV through Dispatcharr

Dispatcharr is part of the default stack and stores its persistent state in
`${CONFIG_DIR}/dispatcharr`. Its web interface is published on port `9191` by
default; `DISPATCHARR_PORT` can override the host port.

The deploy configures the complete integration automatically:

- creates the first Dispatcharr administrator when needed and stores its
  generated credentials in
  `/volume1/docker/media-stack/secrets/dispatcharr-admin.txt`
- builds the internal `dominican-iptv` source and FFprobe monitor, combining
  IPTV-org, every IPTV Cat candidate, and the repository's official-source
  catalog
- creates the refreshable `Republica Dominicana (combinada)` M3U account
- groups duplicate names as ordered fallback streams instead of discarding them
- probes video and audio every six hours and classifies streams as stable,
  intermittent, silent, geoblocked, testing, or dead
- keeps transient failures, but removes a continuously dead source from the
  generated playlist after seven days
- creates the `Dominicana - Estables` and `Dominicana - Todos` channel profiles;
  stable channels use numbers starting at 1, experimental channels at 501, and
  geoblocked channels at 901
- creates an AAC compatibility profile and assigns it only when FFprobe detects
  an audio codec that benefits from conversion while copying the video
- imports the Dominican `EPGShare01` XMLTV feed every 24 hours with explicit
  aliases for the principal national channels
- configures Jellyfin's M3U tuner as
  `http://dispatcharr:9191/output/m3u`
- configures Jellyfin's XMLTV provider as
  `http://dispatcharr:9191/output/epg`
- starts Jellyfin's authenticated `Refresh Guide` task using the existing,
  local-only Jellyfin integration key already stored by Seerr, then waits for
  it to complete so channel additions appear immediately

The interfaces remain available from the LAN at:

```text
http://<NAS address>:9191
```

IPTV Cat does not publish a single stable country-playlist URL. The internal
source service reads its public country pages, resolves an individual IPTV Cat
link only when that channel is played, and caches the generated list, resolved
links, and health history under `${CONFIG_DIR}/dominican-iptv`. Resolver entries
expire after six hours and are refreshed early after repeated failures. If an
upstream refresh fails, the last successful playlist remains available.

`dominican-iptv-sources.json` is the version-controlled catalog for official
streams, EPG aliases, required geographic route, and page provenance. An
official source that requires Dominican egress is not exported until that route
has been explicitly enabled.

The playlist consumed inside the stack is:

```text
http://dominican-iptv:8080/playlist.m3u
```

These are public community streams. A channel can still be temporarily down,
geoblocked, silent, or incompatible with a particular player; exhaustive and
guaranteed carriage requires a licensed IPTV provider.

Reapply the integration without a full deployment with:

```bash
make configure-iptv
```

Run an immediate full signal and audio audit with:

```bash
make audit-iptv
```

The continuous monitor intentionally requires repeated failures before marking
a never-working source dead. A source that worked previously becomes
`intermittent` rather than being removed, because temporary broadcaster outages
are common.

### Optional Dominican Tailscale exit node

The `dominican-exit` Compose profile is prepared but disabled. After the remote
Raspberry Pi advertises a Tailscale exit node:

1. set `DOMINICAN_TAILSCALE_EXIT_NODE` to its Tailscale IP or stable name;
2. place a reusable Tailscale auth key only in the NAS `.env` and set
   `DOMINICAN_TAILSCALE_AUTHKEY`;
3. set `DOMINICAN_EXIT_NODE_ENABLED=1`;
4. start with `docker compose --profile dominican-exit up -d`;
5. run `make audit-iptv` and `make configure-iptv`.

Only the official-stream relay shares the Tailscale network namespace. Jellyfin,
Dispatcharr, and unrelated NAS traffic keep their normal Canadian route. The
relay rewrites HLS manifests so playlists and media segments both traverse the
Dominican exit; it rejects destinations outside the configured broadcaster
host.

The equivalent manual UI operation is **Jellyfin Dashboard → Scheduled Tasks →
Live TV → Refresh Guide → Start**. It is now automated by
`configure-jellyfin-livetv.py`; use `--skip-guide-refresh` only when an
immediate Jellyfin refresh is intentionally unwanted.

Jellyfin and Dispatcharr share the `media-stack` Docker network, so URLs copied
for Jellyfin should use `http://dispatcharr:9191` as the host when possible.
Browser access continues to use the NAS address and published port.

Jellyfin currently presents Live TV as a mostly flat channel list even when
the M3U contains group metadata. Keep the exported channel profile small and
use clear channel names and channel-number ranges for practical browsing.

## Profilarr Pilot

Profilarr is not part of the default stack lifecycle.

The repository includes an optional pilot integration so it can be evaluated
without replacing the existing Recyclarr + custom-script workflow.

The pilot is intentionally scoped as:

- optional Docker Compose profile
- separate config directory under `${CONFIG_DIR}/profilarr`
- optional deploy hook through `PROFILARR_SYNC_ON_DEPLOY=1`
- no changes to Sonarr, Radarr, qBittorrent, Seerr, or cleanup automation

Start the pilot manually with:

```bash
docker compose \
  --env-file stacks/media/env/.env \
  -f stacks/media/compose.yaml \
  --profile profilarr up -d
```

Default pilot image channel:

```text
ghcr.io/dictionarry-hub/profilarr:latest
ghcr.io/dictionarry-hub/profilarr-parser:latest
```

If you want to test a specific release, override `PROFILARR_TAG` in
`stacks/media/env/.env`.


This keeps the evaluation reversible and isolated from the production
configuration path.

Bootstrap or recover the Profilarr admin credentials automatically with:

```bash
make configure-profilarr
```

Apply the safe pilot configuration automatically with:

```bash
make configure-profilarr-pilot
```

Run the full optional Profilarr automation flow with:

```bash
make sync-profilarr
```

Preview it with:

```bash
make dry-run-sync-profilarr
```

Preview the pilot actions without applying them with:

```bash
make dry-run-configure-profilarr-pilot
```

Current assessment:

- Profilarr works well as a generic sync surface for quality profiles,
  release-group logic, and media-management presets
- Profilarr does not currently replace the repository-managed
  Spanish-language ranking policy
- Profilarr is instance-oriented and does not model separate logical targets
  on the same Radarr instance; the live pilot rejected a second target for
  Kids Movies with `This instance target is already configured`

Recommended pilot scope:

- `Sonarr Main`
- `Radarr Movies`

Keep outside Profilarr for now:

- `Latino > Castellano > English/original`
- Kids Movies routing on the shared Radarr instance
- qBittorrent, Seerr, cleanup, and private-tracker automation

## Spanish Language Upgrade Policy

The media stack intentionally prefers:

```text
Latino > Castellano > English/original
```

This is not a simple "prefer Spanish" rule.

The repository-managed implementation is designed to:

- keep Latino as the strongest preference
- allow Castellano as the next-best Spanish fallback
- allow English/original when neither preferred Spanish variant exists
- keep monitoring and upgrade to a better language match later
- handle token-aware title detection rather than unsafe substring matching

Custom formats include:

- `[Latino] Spanish Latino`
- `[Latino] Spanish Latino + English`
- `[Spanish] Castellano`
- `[Latino] French Bonus`
- `[Audio] Audio Description`

Current scores:

```text
[Latino] Spanish Latino             7000
[Latino] Spanish Latino + English   7000
[Spanish] Castellano                6000
[Latino] French Bonus                250
[Audio] Audio Description         -10000
```

This allows the stack to:

1. download an acceptable fallback release
2. continue monitoring for a better Latino release
3. replace the fallback when a better Castellano or Latino candidate becomes
   available

## Sonarr Spanish Audit and Upgrades

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

## Radarr Spanish Audit and Upgrades

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

Imported torrents have an automated retention policy. Public torrents are
removed after a confirmed Sonarr/Radarr import and 30 minutes of seeding.
Known private torrents are removed only after a confirmed import, an explicit
private flag, a recognized tracker policy, and their full per-torrent seeding
limit. Unknown/private torrents without a finite limit, incomplete torrents,
Force Start torrents, and unconfirmed imports are skipped. The job runs every
15 minutes. The guarded title-matched import workflow is also recognized by a
verified download-to-library hardlink, because Sonarr's rescan does not create
a normal qBittorrent download-history record. Preview it with:

```bash
make dry-run-cleanup-public-imported
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

One live Sonarr warning was intentionally resolved on 2026-08-31 by skipping
the default Sonarr language custom-format group that already assigned
`Language: Not Original`, because the repository keeps a local override for
that same custom format. This avoids duplicate-score warnings during sync
while preserving the intended language behavior.

Run manually with:

```bash
make sync-recyclarr
```

Custom local formats are preserved through configured exclusion patterns.

The optional Profilarr pilot can also be synchronized automatically during
`make deploy` by setting:

```text
PROFILARR_SYNC_ON_DEPLOY=1
```

in the NAS-side media environment file.

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
12. optionally synchronizes Profilarr when `PROFILARR_SYNC_ON_DEPLOY=1`

## Live Validation

Run a quick live service check on the NAS:

```bash
make check-media-live
```

Audit live Seerr routing:

```bash
make audit-seerr
```

Audit one retained Seerr request against its Sonarr or Radarr item. This
verifies identity-based routing and confirms the library item is managed below
`/data/Media`; pair it with the hardlink audit for storage validation:

```bash
make audit-seerr-request-flow REQUEST_ID=37
```

Audit Bazarr before removing compatibility mounts:

```bash
make audit-bazarr
```

Audit every compatibility-mount consumer and the qBittorrent inventory before
planning any removal. A non-zero result is expected while a torrent still
uses `/downloads`; the command is read-only and never removes a mount or a
torrent:

```bash
make audit-legacy-mounts
```

Audit recent hardlink-backed imports automatically:

```bash
make audit-hardlinks
```

Audit private-tracker seeding protection:

```bash
make audit-private-trackers
```

Verify that a real download/import pair is a hardlink:

```bash
make verify-hardlinks \
  DOWNLOAD="/data/Downloads/complete/tv/Example/file.mkv" \
  LIBRARY="/data/Media/TV Shows/Example/Season 01/file.mkv"
```

Cleanup scripts now fail closed if a destructive run would remove more than
ten downloads at once, unless the operator explicitly raises the limit with
`--max-delete` after reviewing a dry run.

If you want to separate normal stale cleanup from dangerous-download
remediation, use:

```bash
make dry-run-cleanup-sonarr-dangerous
make dry-run-cleanup-radarr-dangerous
make dry-run-cleanup-sonarr-normal
make dry-run-cleanup-radarr-normal
```

## Periodic Observability

Install the repository-managed observability timers on the NAS with:

```bash
make install-media-observability
```

This installs:

- a 30-minute live health audit timer
- a 12-hour hardlink audit timer
- a 15-minute public-import cleanup timer, with a 30-minute seed retention
- log output at `/volume1/docker/media-stack/logs/media-observability.log`

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
