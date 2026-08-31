# Claude Working Notes

Last updated: 2026-08-30

Read this file before making homelab media-stack changes from Claude.

## Canonical Context

Start with:

- `docs/HOMELAB_MEDIA_CONTEXT.md`
- `docs/profilarr-assessment.md`
- `stacks/media/README.md`

## Current Repository Reality

- main release: `v0.28.0`
- follow-on evaluation branch: `codex/profilarr-pilot`
- NAS SSH alias: `ssh ugreen-nas`
- primary repo: `~/home-labs/homelab`

## Completed Baseline

The following work is already complete and validated:

- Spanish-language upgrade policy:
  `Latino > Castellano > English/original`
- `/data` storage migration for hardlink-safe Sonarr/Radarr imports
- compatibility mounts `/downloads` and `/media` intentionally still present
- Seerr automation for Sonarr, Radarr Movies, and Radarr Kids Movies
- Milnueve private-tracker protections and cleanup safeguards

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

## Guardrails

- do not reset, restore, stash, or discard user changes
- do not remove compatibility mounts `/downloads` or `/media` yet
- do not weaken Milnueve/private-tracker seeding protections
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
