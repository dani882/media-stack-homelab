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
- Force Start torrents are never removed automatically
- destructive cleanup now refuses large batches unless the operator
  explicitly raises `--max-delete`
- dangerous-file cleanup still honors private-tracker seeding obligations

Always preview cleanup before a destructive run.

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
