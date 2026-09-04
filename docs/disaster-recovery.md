# Disaster Recovery

Last updated: 2026-09-04

This document is the short disaster-recovery checklist for the media stack.

## Recovery Order

1. Restore the latest known-good backup
2. Bring the media stack up
3. Reapply managed configuration
4. Revalidate live services
5. Revalidate Seerr routing
6. Revalidate hardlinks
7. Revalidate private-tracker safety constraints
8. Revalidate Dominican Live TV, stream health state, and guide data

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
make configure-iptv
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
make audit-iptv
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

## Dominican IPTV recovery notes

The backup includes `${CONFIG_DIR}/dominican-iptv`, which contains the last
successful generated playlist, IPTV Cat resolver cache, and stream-health
history. Restoring it avoids treating every source as unverified after a NAS
recovery. It is still safe to rebuild this state with `make audit-iptv` if the
cache is unavailable.

After restore, `make configure-iptv` recreates the Dispatcharr account,
fallback relationships, channel profiles, number ranges, audio profile, EPG
source and mappings, plus the Jellyfin M3U/XMLTV configuration. The optional
Tailscale state lives under `${CONFIG_DIR}/tailscale-dominican-exit`; its auth
key remains in the NAS `.env` and must never be placed in a backup intended for
untrusted storage or committed to Git.
