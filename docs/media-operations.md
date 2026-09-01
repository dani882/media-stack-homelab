# Media Stack Operations

Last updated: 2026-08-31

This note is the short operational runbook for the media stack.

## Source of Truth

Use the following ownership model when changing behavior:

- repository JSON/XML-backed Servarr settings:
  Sonarr, Radarr, Seerr, qBittorrent, and root-folder routing
- Recyclarr:
  TRaSH-backed synchronization plus repository-managed exceptions
- Profilarr pilot:
  optional generic quality-profile sync for selected instances
- repository-managed language logic:
  `Latino > Castellano > English/original`
- repository-managed cleanup logic:
  private-tracker protection, H&R-safe behavior, and dangerous-download
  cleanup

Do not move the language policy, Seerr routing, qBittorrent category policy,
or private-tracker safeguards into Profilarr.

## Routine Commands

Validate repository state locally:

```bash
make check
```

Validate live service reachability on the NAS:

```bash
make check-media-live
```

Audit Seerr routing and profile bindings:

```bash
make audit-seerr
```

Audit Bazarr for legacy mount assumptions:

```bash
make audit-bazarr
```

Audit private-tracker protection without exposing announce URLs or passkeys:

```bash
make audit-private-trackers
```

This is also part of the 30-minute media-stack health audit. It reports the
short torrent hash, tracker name, configured seeding requirement, and time
remaining. It fails safely for an unrecognized private tracker, a missing
finite seed limit, or a limit below Milnueve's 96-hour / RetroToon's 72-hour
policy. For RetroToon, it also alerts when the remaining seed time cannot fit
within the tracker's ten-day completion window. It never pauses, removes, or
otherwise changes torrents.

Audit recent hardlink-backed imports automatically:

```bash
make audit-hardlinks
```

Synchronize Recyclarr:

```bash
make sync-recyclarr
```

Synchronize the optional Profilarr pilot:

```bash
make sync-profilarr
```

Preview the optional Profilarr pilot sync:

```bash
make dry-run-sync-profilarr
```

Install the periodic media observability timers on the NAS:

```bash
make install-media-observability
```

Verify a real hardlink import end-to-end:

```bash
make verify-hardlinks \
  DOWNLOAD="/data/Downloads/complete/tv/Example/file.mkv" \
  LIBRARY="/data/Media/TV Shows/Example/Season 01/file.mkv"
```

For completed RetroToon packs that Sonarr cannot match automatically, preview
the strict title-matched helper first. It never guesses localized titles or
multi-episode files:

```bash
make dry-run-import-sonarr-title-matched SERIES_ID=31 \
  SOURCE="/volume1/Family/Downloads/complete/tv/Las Supernenas (1992)"
```

Use `make import-sonarr-title-matched` only after reviewing the preview. It
creates hardlinks, retains the source for private-tracker seeding, and asks
Sonarr to rescan the series.

## Seerr to Jellyfin browser links

Seerr uses `jellyfin:8096` only for its internal Docker connection and
manages `http://10.0.0.123:8899` as Jellyfin's external hostname. This keeps
the API traffic inside Docker while `Play on Jellyfin` opens a LAN-reachable
address in macOS browsers. `make audit-seerr` verifies the external URL along
with library and Servarr routing.

## Recovery

Recover or bootstrap Profilarr admin credentials:

```bash
make configure-profilarr
```

Reapply the pilot sync configuration:

```bash
make configure-profilarr-pilot
```

Reapply Sonarr/Radarr repository-managed settings:

```bash
make configure-servarr
make configure-seerr
make configure-qbittorrent
```

Recover the full media-stack configuration:

```bash
make restore BACKUP="/volume1/docker/media-stack/backups/..."
```

## Cleanup Guardrails

Cleanup is intentionally conservative.

- private torrents are not removed unless the torrent reports a finite,
  positive seeding time limit and that limit has been satisfied
- Milnueve currently requires 96 hours; RetroToon requires 72 hours. Both
  limits are propagated per torrent through Prowlarr and are honored by the
  cleanup guard
- Force Start torrents are never removed automatically
- destructive cleanup now refuses large batches unless the operator
  explicitly raises `--max-delete`
- dangerous-file cleanup still honors private-tracker seeding obligations
- public torrents are removed automatically only after a recorded Sonarr or
  Radarr import and 30 minutes of seeding; the 15-minute job skips anything
  private, incomplete, Force Start, or not explicitly identified as public

Always preview cleanup before a destructive run.

## Private Indexers

RetroToon World is an optional private Generic Torznab indexer. It is
configured from the NAS-local Prowlarr secret file alongside Milnueve; its
passkey must never be committed, copied into documentation, or printed.

RetroToon searches are intentionally limited operationally to animation
requests handled by Sonarr/Radarr. Its custom categories are normalized by
Prowlarr to standard TV/Anime and Movies categories. Do not use it as an RSS
autodownload source.

Some RetroToon records have incomplete ID-based Torznab metadata. When an
existing Seerr request cannot be found by Sonarr/Radarr but an exact Prowlarr
title search succeeds, use the guarded helper rather than downloading a
passkey URL manually:

```bash
QUERY='Exact search title' TITLE='Exact release title' INDEXER_ID=8 \
TVDB_ID='expected-tvdb-id' SEED_TIME_MINUTES=4320 \
TAGS='retrotoon-manual,seerr-request-<id>' make grab-prowlarr-release
```

The helper requires one exact match from the nominated indexer, checks the
TVDB ID and minimum seeder count, translates Prowlarr's loopback download URL
only for the Docker network, assigns the normal `tv` category, and applies the
72-hour per-torrent seed limit. It does not expose or persist tracker URLs.

If you want to separate workflows:

```bash
make dry-run-cleanup-sonarr-dangerous
make dry-run-cleanup-radarr-dangerous
make dry-run-cleanup-sonarr-normal
make dry-run-cleanup-radarr-normal
```

## Hardlink Guardrails

Compatibility mounts `/downloads` and `/media` remain intentionally present.

Do not remove them until:

- Bazarr audit is clean
- live consumers have been revalidated
- hardlink verification has passed for recent real imports

## Profilarr Decision

Use Profilarr only where it fits cleanly:

- good fit:
  generic quality profiles, release-group preferences, and selected preset
  sync for `Sonarr Main` and `Radarr Movies`
- keep outside Profilarr:
  Spanish-language ranking, Kids Movies routing on shared Radarr, Seerr
  request routing, qBittorrent category policy, and cleanup logic
