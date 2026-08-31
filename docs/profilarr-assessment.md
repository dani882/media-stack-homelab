# Profilarr Assessment

Last updated: 2026-08-31

This note captures the current evaluation of Profilarr against the live
homelab media stack.

## Executive Summary

Profilarr is promising as a partial replacement for Recyclarr, but it does
not currently replace the full custom policy stack used in this repository.

Recommended scope:

- use Profilarr for generic quality-profile, release-group, and media
  management sync
- treat Profilarr as a complementary layer, not the top-level source of truth
- keep the repository-managed Spanish-language preference logic outside
  Profilarr
- keep separate request-routing and root-folder behavior outside Profilarr
  when a single Radarr instance serves more than one logical workflow

## What Was Validated Live

The Profilarr pilot was brought up successfully on the NAS and reached at:

```text
http://10.0.0.123:6868
```

The live evaluation confirmed:

- Profilarr can connect successfully to `Sonarr Main`
- Profilarr can connect successfully to `Radarr Movies`
- the Dictionarry database and bundled sync surfaces are available
- bundled quality profiles, custom formats, regexes, and media-management
  settings are visible and ready to sync

## What Profilarr Can Replace

Profilarr is a good fit for the generic pieces of the current Recyclarr-like
configuration surface:

- quality profiles
- release-group preferences
- source and codec-oriented custom formats
- media-management presets
- delay-profile synchronization

This makes it a reasonable candidate to replace part of the generic
quality-policy maintenance currently handled through repository-managed
custom formats and profile sync.

## What Profilarr Does Not Replace Yet

### 1. Spanish-Language Upgrade Policy

The current stack intentionally enforces:

```text
Latino > Castellano > English/original
```

The live Profilarr evaluation did not surface built-in profiles, custom
formats, or regex sets that model this preference order directly.

The repository's custom language logic still provides important behavior:

- token-aware Spanish title detection
- explicit precedence for Latino markers over generic Spanish metadata
- Castellano fallback handling
- English/original fallback when preferred Spanish variants are unavailable
- upgrade helpers that intentionally allow language improvements even when
  the candidate quality is otherwise lower

This policy should remain repository-managed for now.

### 2. Multiple Logical Flows on One Radarr Instance

The current stack uses one Radarr instance for more than one logical movie
workflow, including standard Movies and Kids Movies.

Profilarr sync is instance-oriented.

During live testing:

- `Radarr Movies` was added successfully
- a second logical target against the same Radarr URL/API key was tested
- Profilarr rejected the save with:
  `This instance target is already configured`

That means Profilarr currently behaves as a one-target-per-Arr-instance tool
for this use case. It does not model separate logical sync targets for
different root-folder or request-routing behavior inside the same Radarr
instance.

### 3. The Rest of the Operational Stack

Profilarr does not replace the repository-managed operational automation for:

- qBittorrent category and path management
- `/data/Downloads` and `/data/Media` hardlink architecture
- Seerr integration and request routing
- cleanup safety rules
- private-tracker seeding protections
- Milnueve-specific operational safeguards

## Recommended Pilot Scope

The safest pilot is:

1. keep the existing repository-managed Spanish-language policy
2. keep Seerr, qBittorrent, cleanup, and private-tracker logic unchanged
3. evaluate Profilarr only for generic sync on:
   - `Sonarr Main`
   - `Radarr Movies`
4. leave Kids Movies outside the pilot unless the architecture changes to a
   separate Radarr instance

## Recommendation

Proceed with a partial pilot, not a full migration.

Good candidate responsibilities for Profilarr:

- generic quality profiles
- generic custom formats
- generic delay profiles
- generic media-management presets

Keep repository ownership over:

- Spanish language ranking and upgrades
- Radarr multi-workflow routing
- Seerr orchestration
- qBittorrent path/category policy
- hardlink-safe storage behavior
- private-tracker protections
