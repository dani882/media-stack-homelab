# Claude Working Notes

Last updated: 2026-09-01

Read this file before making homelab media-stack changes from Claude.

## Canonical Context

Start with:

- `docs/HOMELAB_MEDIA_CONTEXT.md`
- `docs/profilarr-assessment.md`
- `stacks/media/README.md`

## Current Repository Reality

- main release: `v0.28.0`
- current working baseline: `main`
- NAS SSH alias: `ssh ugreen-nas`
- primary repo: `~/home-labs/homelab`

## Completed Baseline

The following work is already complete and validated:

- Spanish-language upgrade policy:
  `Latino > Castellano > English/original`
- `/data` storage migration for hardlink-safe Sonarr/Radarr imports
- compatibility mounts `/downloads` and `/media` intentionally still present
- Servarr root folders are reconciled to the `/data/Media` declarations, so
  Seerr must not offer legacy `/media/...` destinations after configuration
- Seerr automation for Sonarr, Radarr Movies, and Radarr Kids Movies
- Milnueve, RetroToon, and Torrent Haven private-tracker protections and
  cleanup safeguards

## Profilarr Pilot Reality

Profilarr is a partial-fit pilot, not a full replacement.

Validated live:

- Profilarr reachable at `http://10.0.0.123:6868`
- Sonarr can be linked
- one Radarr instance can be linked

Current limitation:

- Profilarr rejected a second logical target against the same Radarr
  instance with `This instance target is already configured`

Interpretation:

- good candidate for generic quality-profile/custom-format sync
- not a drop-in replacement for the repository-managed Spanish-language
  logic
- not a drop-in replacement for multi-workflow routing on one Radarr
  instance

## Recyclarr Note

Validated live on 2026-08-31:

- Recyclarr itself was working correctly
- Sonarr had one duplicate-score warning for
  `Language: Not Original (ae575f95ab639ba5d15f663bf019e3e8)`
- cause: the default guide-backed Sonarr language group already assigned
  that CF with the guide score, while the local config also assigned it
  explicitly with score `0`
- fix: skip Sonarr custom format group
  `74aff4168620ed49dcc67e92b2c2a5b4` so the CF is assigned only once
- live Sonarr and Radarr preview syncs both completed cleanly after the fix

## Guardrails

- do not reset, restore, stash, or discard user changes
- do not remove compatibility mounts `/downloads` or `/media` yet
- do not weaken Milnueve/private-tracker seeding protections
- public torrents may be removed only after a confirmed Sonarr/Radarr import
  and 30 minutes of seed time; the automated job must fail closed for private
  or ambiguously classified torrents
- qBittorrent keeps a three-download limit, but stalled/slow torrents stop
  consuming a slot after 60 seconds; do not use Force Start as queue control
- RetroToon is a private Generic Torznab indexer with a 72-hour seed-time
  requirement to be met within ten days of completion; its passkey is
  NAS-local only and must never be logged or committed. The private-tracker
  audit alerts if the remaining seed time cannot fit in that window.
- when a private indexer cannot resolve a normal *arr ID search, retain the
  Seerr request and use the guarded `make grab-prowlarr-release` path with an
  exact title, a unique request tag, and TVDB (TV) or TMDB (movie) identity
  validation; do not bypass the private-tracker policy with manual URLs
- completed RetroToon TV packs with non-standard numbering may use
  `make dry-run-import-sonarr-title-matched` followed by its explicit apply
  target; it hardlinks only unique English title matches and leaves ambiguous
  or multi-episode files untouched
- `make audit-legacy-mounts` is the authoritative read-only check before a
  future compatibility-mount removal. At the latest audit, Sonarr/Radarr
  roots were already under `/data/Media`, but old-path qBittorrent torrents
  still required `/downloads`; do not remove either legacy mount.
- `make audit-seerr-request-flow REQUEST_ID=...` confirms a retained Seerr
  request maps by TVDB/TMDB identity to a `/data/Media` Sonarr/Radarr item.
  Pair it with `make audit-hardlinks` to validate the storage layer.
- Torrent Haven uses Prowlarr's native `torrenthaven-api` definition. Its API
  token belongs only in `prowlarr-private-indexers.json` on the NAS; enforce
  4320 minutes for releases and packs. Its rules prohibit DHT/PEX and extra
  tracker URLs. A real Torrent Haven torrent was verified `private=true` with
  only `torrenthaven.org` announced, so keep qBittorrent's public-friendly
  global discovery settings unchanged and validate those per torrent.
- Torrent Haven's Madagascar test was imported as a hardlink and is seeding
  with its 4320-minute limit, but its filename claimed 1080p while MediaInfo
  detected 960x540 (`WEBDL-480p`) and English audio only. Treat MediaInfo and
  *arr's resulting quality/languages as authoritative over release titles.
- do not assume `ugreen-nas` resolves in the browser on macOS; use the IP
  when needed for browser access
- Seerr keeps `jellyfin:8096` for internal Docker traffic and dynamically
  derives Jellyfin's browser-facing mDNS URL from the NAS hostname plus the
  published Docker port; verify it with `make audit-seerr`
- prefer automation over manual NAS steps

## Recommended Direction

If extending the Profilarr pilot:

1. keep the current Spanish-language policy repository-managed
2. pilot Profilarr only for generic sync surfaces
3. treat `Sonarr Main` and `Radarr Movies` as the safe pilot scope
4. keep Kids Movies, Seerr routing, qBittorrent policy, and cleanup logic
   outside Profilarr unless the architecture changes

## Useful Commands

- `make check`
- `make check-media-live`
- `make audit-bazarr`
- `make audit-seerr`
- `make audit-private-trackers`
- `make audit-legacy-mounts`
- `make audit-seerr-request-flow REQUEST_ID=37`
- `make audit-hardlinks`
- `make sync-recyclarr`
- `make sync-profilarr`
- `make install-media-observability`
- `make verify-hardlinks DOWNLOAD="..." LIBRARY="..."`
