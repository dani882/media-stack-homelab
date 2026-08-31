# Disaster Recovery

Last updated: 2026-08-31

This document is the short disaster-recovery checklist for the media stack.

## Recovery Order

1. Restore the latest known-good backup
2. Bring the media stack up
3. Reapply managed configuration
4. Revalidate live services
5. Revalidate Seerr routing
6. Revalidate hardlinks
7. Revalidate private-tracker safety constraints

## Restore

Preview first:

```bash
make dry-run-restore \
  BACKUP=/volume1/docker/media-stack/backups/media-stack-YYYYMMDDTHHMMSSZ.tar.zst
```

Apply:

```bash
make restore \
  BACKUP=/volume1/docker/media-stack/backups/media-stack-YYYYMMDDTHHMMSSZ.tar.zst
```

## Reapply Managed Configuration

```bash
make configure-prowlarr
make configure-qbittorrent
make configure-servarr
make configure-seerr
make sync-recyclarr
make sync-profilarr
```

If the Profilarr pilot is not enabled on that host, skip the final command.

## Revalidate Live State

```bash
make check-media-live
make audit-seerr
make audit-bazarr
make audit-hardlinks
```

For a known real import pair:

```bash
make verify-hardlinks \
  DOWNLOAD="/data/Downloads/..." \
  LIBRARY="/data/Media/..."
```

## Private-Tracker Safety

Before any destructive cleanup:

- run the dry-run cleanup targets first
- confirm private torrents still report finite positive seeding limits
- confirm no private torrent has unmet seeding obligations
- do not re-enable Force Start automatically

## Compatibility Mounts

Do not remove `/downloads` or `/media` during disaster recovery.

Treat legacy mount removal as a separate follow-up change after live
validation is complete.
