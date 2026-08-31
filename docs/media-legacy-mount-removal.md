# Legacy Mount Removal Checklist

Last updated: 2026-08-31

Compatibility mounts `/downloads` and `/media` are still intentionally
present.

Remove them only in a later, separate change after all items below are green.

## Required Preconditions

- `make check` passes
- `make check-media-live` passes
- `make audit-bazarr` passes
- `make audit-seerr` passes
- `make audit-hardlinks` passes
- `make verify-hardlinks` passes for at least one recent real import pair
- qBittorrent new downloads still land under `/data/Downloads/...`
- Sonarr imports still land under `/data/Media/TV Shows`
- Radarr imports still land under `/data/Media/Movies` or
  `/data/Media/Kids Movies`
- remaining incomplete old-path torrents have been reviewed individually

## Consumer Review

Review each consumer before removing mounts:

- Sonarr
- Radarr
- qBittorrent
- Bazarr
- Seerr
- Jellyfin
- cleanup scripts
- backup/restore scripts
- watchdog and observability scripts

## Explicit Non-Goals

Legacy mount removal must not:

- redesign qBittorrent categories
- weaken private-tracker protections
- change the `Latino > Castellano > English/original` policy
- change Seerr routing behavior
- turn hardlink-safe storage migration into a broader media-layout rewrite
