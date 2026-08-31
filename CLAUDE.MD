# Claude Working Notes

Last updated: 2026-08-31

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
- Seerr automation for Sonarr, Radarr Movies, and Radarr Kids Movies
- Milnueve and RetroToon private-tracker protections and cleanup safeguards

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
- RetroToon is a private Generic Torznab indexer with a 72-hour seed-time
  requirement; its passkey is NAS-local only and must never be logged or
  committed
- do not assume `ugreen-nas` resolves in the browser on macOS; use the IP
  when needed for browser access
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
- `make audit-hardlinks`
- `make sync-recyclarr`
- `make sync-profilarr`
- `make install-media-observability`
- `make verify-hardlinks DOWNLOAD="..." LIBRARY="..."`
