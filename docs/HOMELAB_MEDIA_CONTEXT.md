# Homelab Media Stack — Exhaustive Working Context / Canonical Checkpoint

Last updated: 2026-09-04

This document is the canonical handoff/checkpoint for the current homelab media-stack work.

It is intentionally verbose.

Historical note:

This file began as the canonical checkpoint for the
`feat/spanish-language-upgrades` branch. The underlying work from that
branch was later completed, merged, and released as `v0.28.0`.

It now serves two purposes:

- preserve the detailed migration history and validation trail
- provide current handoff notes for follow-on work such as the Profilarr
  pilot

Current follow-on branch after the `v0.28.0` release:

`main`

The goal is that ChatGPT, Codex, or another engineer can read this file and understand:
- what the repository is trying to achieve,
- what has already been changed,
- what has already been validated live on the NAS,
- what failed and why,
- what is still intentionally unresolved,
- what should NOT be changed,
- what remains to be validated,
- which torrents/private-tracker obligations must be preserved,
- what the current branch contains,
- and what safe next steps look like.

Before making changes, read this entire file.

---

# 0B. Dominican IPTV / Dispatcharr Checkpoint — 2026-09-04

This is the current checkpoint for the Dominican Republic Live TV work
completed and pushed to `main` in commit:

`e6f04f2 feat(media): improve Dominican IPTV reliability and Jellyfin integration`

Repository and Git state after the IPTV implementation and documentation
pushes:

- branch: `main`
- implementation commit: `e6f04f2`
- documentation and canonical-memory commit: `916f50e`
- release containing this work: `v0.29.0` (prepared after the documentation
  follow-up on 2026-09-04)

## Implemented architecture

The work began after the user observed that the first Jellyfin setup exposed
only a small subset of Dominican channels and that some returned Jellyfin's
fatal playback error or lacked audio. The investigation distinguished three
different conditions: volatile community URLs, codec/audio compatibility, and
true geographic restrictions. Antena 7's official live page was inspected and
its official HLS endpoint was recorded in the catalog with its page referer and
origin metadata, but it remained inaccessible without Dominican egress.

The user logged into Dispatcharr so its live configuration could be inspected.
Any settings initially explored through the web UI were subsequently expressed
in Compose, catalog data, or idempotent repository scripts. There must be no
required UI-only step for normal deployment or recovery.

Dispatcharr is part of the default media Compose stack. Two additional
repository-built services are present:

- `dominican-iptv`: generates and serves the combined internal M3U playlist
- `dominican-iptv-monitor`: runs concurrent FFprobe video/audio audits every
  six hours

The generator combines:

- the IPTV-org Dominican Republic playlist
- every candidate discovered on the IPTV Cat Dominican Republic pages
- curated official sources in
  `stacks/media/dominican-iptv-sources.json`

Duplicate sources are deliberately preserved. `configure-dispatcharr.py`
normalizes equivalent names into one visible channel and attaches the
remaining sources as ordered `ChannelStream` fallbacks. It does not discard a
working alternative simply because another URL has the same channel name.

IPTV Cat wrapper resolutions are cached for six hours. Repeated failures can
force an earlier resolution refresh. The last successful generated playlist
continues to be served when an upstream catalog refresh fails.

Health classifications are:

- `stable`: FFprobe found video and an audio stream
- `silent`: video works but no audio stream was detected
- `intermittent`: the source worked previously but failed the latest audit
- `testing`: not enough successful or failed observations yet
- `geo-blocked`: marked geographic or identified as such by the probe
- `dead`: a never-working source failed at least three consecutive audits

A temporary failure is not deleted. A dead source remains in health history
and is omitted from the generated playlist only after seven days of continuous
dead state. This conservative behavior is intentional because several public
broadcasters fail briefly and recover later.

## Dispatcharr and Jellyfin configuration

The idempotent Dispatcharr configurator creates or maintains:

- M3U account `Republica Dominicana (combinada)`
- ordered per-channel fallback streams
- `Dominicana - Estables` and `Dominicana - Todos` channel profiles
- channel numbers beginning at 1 (stable), 501 (experimental), and 901
  (geoblocked)
- FFmpeg profile `IPTV - Compatibilidad AAC`, assigned only when an audited
  audio codec needs conversion; video remains stream-copied
- EPG source `Republica Dominicana (EPGShare01)` using the DO1 XMLTV feed
- explicit national-channel EPG aliases maintained in the source catalog

The Jellyfin configurator maintains:

- M3U tuner: `http://dispatcharr:9191/output/m3u`
- XMLTV provider: `http://dispatcharr:9191/output/epg`
- shared-stream and conservative transcoding options
- authenticated execution of Jellyfin's `Refresh Guide` scheduled task

The Jellyfin API credential is reused from the existing NAS-local integration
state; it is not placed in Git.

## Live validation from this session

The full stack deployment completed successfully on the UGREEN NAS. Final live
checks reported:

These counts are a deployment-time snapshot and will change as public
broadcasters and IPTV Cat entries appear, recover, or expire.

- `dominican-iptv`: healthy
- `dominican-iptv-monitor`: running
- Dispatcharr: running
- Jellyfin: healthy
- 676 audited upstream streams
- 296 stable sources
- 365 sources still testing
- 15 geoblocked sources
- 361 visible canonical channels
- 205 channels with more than one attached source
- 326 total alternative/fallback links beyond the primary sources
- 221 channels in the stable number range
- 138 channels in the experimental number range
- 2 channels in the geoblocked number range
- EPG import status: success
- 56 EPG channel entries available
- 8 Dominican national channels explicitly mapped after correcting aliases,
  including the `Tele Antillas` spaced-name variant
- Jellyfin guide refresh completed after the final EPG mapping pass

The final repository validation executed `make check`: Compose validation
passed and all 133 automated tests passed. A Python `ResourceWarning` emitted
by a test-created HTTP redirect object remains non-fatal; it did not fail the
suite.

## Files that own this behavior

- `stacks/media/compose.yaml`
- `stacks/media/dominican-iptv.Dockerfile`
- `stacks/media/dominican-iptv-sources.json`
- `scripts/dominican-iptv.py`
- `scripts/configure-dispatcharr.py`
- `scripts/configure-jellyfin-livetv.py`
- `scripts/deploy.sh`
- `scripts/backup.sh`
- `scripts/restore.sh`
- `tests/test_dominican_iptv.py`
- `tests/test_configure_dispatcharr.py`
- `tests/test_configure_jellyfin_livetv.py`

Operational commands:

```bash
make configure-iptv
make audit-iptv
```

The persistent `${CONFIG_DIR}/dominican-iptv` directory is included in backup
and restore. It contains the last successful playlist, resolver cache, and
health history.

## Intentionally pending: Raspberry Pi in the Dominican Republic

The optional `dominican-exit` Compose profile is implemented but intentionally
inactive. The user does not yet have the Raspberry Pi. When it is installed at
the parents' home, configure it as a Tailscale exit node and use Ethernet when
possible. Then place the exit-node name/IP and reusable auth key only in the
NAS `.env`, set `DOMINICAN_EXIT_NODE_ENABLED=1`, and start the
`dominican-exit` profile.

Only `dominican-iptv-dr`, the official HLS relay, shares the Tailscale client
network namespace. Dispatcharr, Jellyfin, and unrelated NAS traffic must keep
their normal Canadian route. The relay rewrites master/media manifests,
segments, and key URLs and rejects hosts outside the configured broadcaster
host.

Antena 7's official stream is catalogued but is not exported through the
official relay until Dominican egress is enabled. Public community Antena 7
sources may remain visible as testing or geoblocked in the complete profile.
Do not claim that the official Antena 7 source works from Canada before the
remote exit node has been installed and validated.

## Safe follow-up work

- Install and validate the Raspberry Pi Tailscale exit node when hardware is
  available.
- Run `make audit-iptv` and `make configure-iptv` after enabling it.
- Recheck the official Antena 7 HLS child hosts; add explicit allowed hosts to
  the catalog only if the real manifest uses additional broadcaster CDNs.
- Periodically review sources still in `testing`; do not aggressively delete
  intermittent public broadcasters.
- Allow at least three audit observations before treating a never-working
  source as dead; the first live snapshot naturally left many sources in
  `testing`.
- A licensed provider remains the only path to guaranteed exhaustive carriage;
  the current integration intentionally uses public/community sources.

---

# 0A. Current State After `v0.28.0`

The original branch work described throughout this file is now complete.

Completed and released on `main` as `v0.28.0`:

- Spanish-language upgrade policy:
  `Latino > Castellano > English/original`
- `/data` migration for hardlink-safe imports
- qBittorrent namespace migration for new downloads
- Sonarr and Radarr root-folder migration to `/data/Media/...`
- Seerr fixes and validation
- live hardlink proof for Sonarr and Radarr

Follow-up note: compatibility mounts remain available, but the managed
Servarr root-folder reconciliation removes obsolete `/media/...` root-folder
entries once no library record references them. This prevents Seerr from
offering legacy destinations while preserving compatibility for consumers
that still require the mount.

RetroToon manual-selection note: its Generic Torznab endpoint can return an
exact title search while failing an ID-based Sonarr search. In that case, keep
the Seerr request as the request record and use `make grab-prowlarr-release`
with an exact title, TVDB validation, a unique request tag, and the required
4320-minute seed limit. The helper must never log tracker URLs or passkeys.

RetroToon rule update: its 72 hours of seeding must be completed within ten
days of completion. `scripts/audit-private-trackers.py` enforces this as an
alert-only deadline check: it never pauses, removes, or changes torrents.

Powerpuff Girls request validation (2026-08-31): the RetroToon torrent
`Las Supernenas (1992)` is private, queued at zero percent, and therefore has
not contributed tracker transfer statistics or library media yet. Sonarr
previously imported public `Kitsune` season packs before the series was
unmonitored; an inspected season-three file has only an `eng` audio stream.
Do not treat a tracker listing labelled "Spanish, English" as proof that the
default playback audio is Spanish. Keep this series unmonitored until the
RetroToon release completes and its actual streams are inspected.

The incorrectly imported public `Kitsune` torrents and their thirteen
English-only season-three library files were removed with explicit approval.
After the cleanup, Sonarr reports zero episode files for this series and qBittorrent
contains only the protected RetroToon torrent.

Public retention policy: repository-managed automation removes a torrent only
when qBittorrent explicitly marks it public, Servarr history confirms import,
and it has seeded for at least 30 minutes. It runs every 15 minutes with a
maximum of ten deletions per run and skips all private or ambiguous torrents.
It was deployed and verified on 2026-08-31: the first run removed seven
eligible public torrents and retained all three Milnueve torrents.

qBittorrent queue policy: the active-download limit remains three, but slow
or stalled torrents below 2 KiB/s for 60 seconds do not consume a slot. This
prevents unavailable torrents from blocking the next eligible download without
requiring Force Start.

The current follow-on work is an optional Profilarr pilot on branch:

`main` (the pilot was merged after validation)

Live Profilarr pilot status at the time of this update:

- Profilarr is running successfully on the NAS
- URL:
  `http://10.0.0.123:6868`
- automated admin bootstrap/recovery exists through
  `make configure-profilarr`
- Sonarr and one Radarr instance were linked successfully during live
  evaluation

Important live conclusion from the Profilarr pilot:

- Profilarr looks viable as a partial replacement for generic Recyclarr-like
  sync surfaces
- Profilarr does not currently replace the repository-managed
  Spanish-language policy
- Profilarr rejected a second logical target for the same Radarr instance
  with `This instance target is already configured`, which means it does not
  directly model separate Movies and Kids Movies flows on the same Radarr
  instance

Additional live note from 2026-08-31:

- Recyclarr preview validation confirmed the stack was healthy overall
- a Sonarr-only warning was traced to duplicate scoring of
  `Language: Not Original (ae575f95ab639ba5d15f663bf019e3e8)`
- the repository fix was to skip Sonarr TRaSH custom format group
  `74aff4168620ed49dcc67e92b2c2a5b4` and keep the repository-managed local
  score assignment
- live preview syncs for both Sonarr and Radarr completed cleanly after that
  change
- new operational commands now exist for:
  `make sync-profilarr`
  `make dry-run-sync-profilarr`
  `make check-media-live`
  `make audit-bazarr`
  `make audit-seerr`
  `make audit-hardlinks`
  `make install-media-observability`
  `make verify-hardlinks DOWNLOAD=... LIBRARY=...`

Additional private-indexer note from 2026-08-31:

- RetroToon World was added successfully through its Generic Torznab endpoint
- it is Prowlarr indexer ID `8`, priority `8`, and requires at least one
  seeder
- its 72-hour requirement is propagated as a `4320` minute seed time for
  torrents and season packs
- live non-grabbing searches through Prowlarr returned valid TV and anime
  results, and the indexer is present in both Sonarr and Radarr
- the RetroToon passkey is stored only in
  `/volume1/docker/media-stack/secrets/prowlarr-private-indexers.json`
- treat that passkey as compromised if it is ever displayed outside the
  tracker or NAS secret store; do not commit or log it
- `make audit-private-trackers` and the 30-minute health timer audit
  Milnueve and RetroToon obligations without logging announce URLs or
  passkeys; unrecognized private trackers fail closed until a policy is added

---

# 0. Historical `v0.28.0` workstream summary

The remainder of this section records the earlier
`feat/spanish-language-upgrades` branch and is retained for migration history.
For current state, use sections 0B and 0A above.

Repository:

`~/home-labs/homelab`

Current branch:

`feat/spanish-language-upgrades`

There were two major workstreams on this historical branch:

1. Language-preference / media-quality policy:
   - desired preference:
     `Latino > Castellano > English/original`
   - add Castellano custom formats
   - permit language-driven upgrades even when the candidate quality is technically lower
   - keep Latino as highest preference
   - preserve compatibility with existing Latino helper logic
   - update Sonarr/Radarr upgrade helpers
   - validate against real Milnueve releases

2. Storage-path / hardlink migration:
   - old container layout:
     `/downloads` and `/media` were separate bind mounts
   - this prevented hardlinks across them even though they are on the same Btrfs filesystem
   - new parent mount:
     `/volume1/Family -> /data`
   - final logical paths:
     `/data/Downloads/...`
     `/data/Media/...`
   - objective:
     qBittorrent keeps seeding from Downloads while Sonarr/Radarr import into Media via hardlinks instead of duplicate copies

The hardlink mechanism has already been proven successfully in Sonarr and Radarr.

Sonarr and Radarr library paths have already been logically migrated to `/data/Media/...` without physically moving files.

qBittorrent has already been recreated with `/data`, and a set of completed torrents has been migrated safely to `/data/Downloads/...`.

The qBittorrent desired configuration for new downloads has also been applied and validated.

Compatibility mounts `/downloads` and `/media` remain intentionally present.

Do NOT remove them yet.

---

# 1. Repository and branch state

Repository:

`~/home-labs/homelab`

Current branch:

`feat/spanish-language-upgrades`

Do not switch branches without first reviewing the working tree.

The current working tree contains intentional uncommitted work.

Known changed/new files from this work include at least:

- `scripts/configure-radarr-policy.py`
- `scripts/media/common/latino.py`
- `scripts/media/common/language.py`
- `scripts/media/upgrade-radarr-latino.py`
- `scripts/media/upgrade-sonarr-latino.py`
- `scripts/servarr_config/custom_formats.py`
- `scripts/migrate-servarr-paths.py`
- `scripts/configure-radarr.py`
- `scripts/configure-seerr.py`
- `scripts/configure-qbittorrent.py`
- `scripts/deploy.sh`
- `scripts/media/cleanup-sonarr-downloads.py`
- `scripts/media/cleanup-radarr-downloads.py`
- `stacks/media/compose.yaml`
- `stacks/media/env/.env`
- `stacks/media/.env.example`
- `stacks/media/qbittorrent/categories.json`
- `stacks/media/qbittorrent/preferences.json`
- `stacks/media/recyclarr/recyclarr.yml`
- `stacks/media/servarr/custom-formats/radarr-latino.json`
- `stacks/media/servarr/custom-formats/sonarr-latino.json`
- `stacks/media/servarr/sonarr/root-folders.json`
- `stacks/media/servarr/radarr/root-folders.json`
- `stacks/media/servarr/radarr/download-clients.json`
- `stacks/media/servarr/sonarr/download-clients.json`
- `tests/test_configure_seerr.py`
- `tests/media/test_language.py`
- possibly other related tests/docs touched during later Codex continuation

Before doing any work:

```bash
cd ~/home-labs/homelab

git branch --show-current
git status --short
git diff --check
git diff --stat
```

Do not:
- reset,
- restore,
- stash,
- checkout another branch,
- discard changes,
- overwrite files blindly.

---

# 2. Validation status

The test suite has been run multiple times during this work.

Known passing state at one checkpoint:

```text
✓ Compose configuration is valid.
...
Ran 57 tests
OK
```

Also:
- `git diff --check` passed
- Seerr tests passed after root-path updates
- language tests passed
- legacy Latino tests passed
- Python compilation checks passed for modified scripts

Before commit or destructive live changes, always run:

```bash
make check
git diff --check
```

For targeted language validation:

```bash
python3 -m unittest -v \
  tests.media.test_language \
  tests.media.test_latino
```

For Seerr:

```bash
python3 -m unittest -v tests.test_configure_seerr
```

---

# 3. NAS / runtime environment

NAS host alias:

`ugreen-nas`

Media stack root on NAS:

`/volume1/docker/media-stack`

Family storage root:

`/volume1/Family`

Physical family layout:

```text
/volume1/Family/
├── Downloads/
└── Media/
    ├── TV Shows/
    ├── Movies/
    └── Kids Movies/
```

Services include:
- Prowlarr
- Sonarr
- Radarr
- Bazarr
- Seerr
- qBittorrent
- Jellyfin
- FlareSolverr
- Recyclarr

Relevant live versions observed:

Sonarr:
`4.0.19.2979`

Radarr:
`6.3.0.10514`

qBittorrent:
`5.2.3`

Jellyfin image:
`jellyfin/jellyfin:10.10.7`

---

# 4. Original Docker storage problem

Original Sonarr/Radarr mounts were:

```text
/volume1/Family/Downloads -> /downloads
/volume1/Family/Media     -> /media
```

From the host, both paths live on the same underlying Btrfs filesystem.

Observed host filesystem/device information:

```text
Filesystem mounted at /volume1/Family
device id: 70
```

Inside Sonarr, old mountinfo showed separate bind mounts:

```text
/Family/Downloads -> /downloads
/Family/Media     -> /media
```

Even though both were backed by the same Btrfs filesystem and same subvolume, attempting:

```bash
ln /downloads/... /media/...
```

failed with:

```text
Cross-device link
```

This is the key reason hardlinks did not work.

The problem was the container mount boundary, not the host filesystem.

---

# 5. New hardlink-safe architecture

New parent mount:

```text
/volume1/Family -> /data
```

This allows both:

```text
/data/Downloads
/data/Media
```

to exist beneath one container mount.

Hardlink tests were performed in Sonarr and Radarr.

Example Sonarr test:

```text
src=/data/Downloads/complete/tv/.hardlink-test-source
dst=/data/Media/.hardlink-test-destination
```

Result:

```text
HARDLINK SUCCESS
same inode
links=2
device=70
```

Radarr test also returned:

```text
HARDLINK SUCCESS
same inode
links=2
device=70
```

This proves the new path architecture solves the original cross-device problem.

---

# 6. Transitional compose strategy

The migration was intentionally done in stages.

Rather than immediately removing old mounts, `/data` was added alongside the existing mounts.

Current transitional intent:

Sonarr:
```text
/config
/data
/downloads
/media
```

Radarr:
```text
/config
/data
/downloads
/media
```

qBittorrent:
```text
/config
/data
/downloads
```

Bazarr:
- legacy `/media` retained
- `/data` also added later for forward compatibility

Jellyfin:
- still consumes legacy media mount
- compatibility path removal is explicitly NOT part of this change

Do NOT remove old `/downloads` or `/media` mounts yet.

---

# 7. Environment changes

Added:

```text
FAMILY_DIR=/volume1/Family
```

to:

- `stacks/media/env/.env`
- `stacks/media/.env.example`

Existing variables remain:

```text
CONFIG_DIR=/volume1/docker/media-stack/config
DOWNLOADS_DIR=/volume1/Family/Downloads
MEDIA_DIR=/volume1/Family/Media
```

NAS live `.env` was updated to contain:

```text
FAMILY_DIR=/volume1/Family
DOWNLOADS_DIR=/volume1/Family/Downloads
MEDIA_DIR=/volume1/Family/Media
```

The NAS compose was manually updated from the repo and backed up as:

```text
/volume1/docker/media-stack/compose.yaml.pre-data-mount
```

Validation:

```bash
sudo docker compose config --quiet
```

Result:

```text
COMPOSE VALID
```

---

# 8. Sonarr / Radarr root-folder migration

The desired library paths changed from:

```text
/media/TV Shows
/media/Movies
/media/Kids Movies
```

to:

```text
/data/Media/TV Shows
/data/Media/Movies
/data/Media/Kids Movies
```

New root folders were created live.

Sonarr:

```text
ID=1 path=/media/TV Shows
ID=2 path=/data/Media/TV Shows
```

Radarr:

```text
ID=1 path=/media/Movies
ID=2 path=/media/Kids Movies
ID=3 path=/data/Media/Movies
ID=4 path=/data/Media/Kids Movies
```

A dedicated migration script was created:

`scripts/migrate-servarr-paths.py`

Purpose:
- migrate entity paths from `/media/...` to `/data/Media/...`
- do not physically move media
- use path update only
- dry-run by default
- use `--apply` to execute
- idempotent
- intended specifically for alias/path migration

---

# 9. Important warning about configure-radarr.py

`scripts/configure-radarr.py` has move behavior using:

```python
{"moveFiles": "true"}
```

That script is appropriate for intentional moves between real Radarr roots, e.g.:

```text
Movies <-> Kids Movies
```

It is NOT appropriate for alias migration:

```text
/media/... -> /data/Media/...
```

because the files are already physically in the correct place.

The alias migration must use the dedicated migration logic with `moveFiles=false`.

---

# 10. Radarr migration results

Geostorm was used as the first canary.

Before:

```text
path: /media/Movies/Geostorm (2017)
rootFolderPath: /media/Movies
hasFile: True
```

Physical file:

```text
inode=293
```

The movie record was updated with:

```text
path=/data/Media/Movies/Geostorm (2017)
rootFolderPath=/data/Media/Movies
moveFiles=false
```

After:

```text
path: /data/Media/Movies/Geostorm (2017)
rootFolderPath: /data/Media/Movies
hasFile: True
```

Same file:

```text
inode=293
```

No physical move occurred.

Then the full Radarr migration was run.

Dry-run before apply:

```text
Would change: 29
Already migrated: 1
```

Apply:

```text
Mode: APPLY
Would change: 29
Already migrated: 1
```

Final dry-run:

```text
Would change: 0
Already migrated: 30
```

Spot checks included:

```text
Geostorm
/data/Media/Movies/Geostorm (2017)

Resident Evil: Death Island
/data/Media/Movies/Resident Evil - Death Island (2023)

Toy Story 5
/data/Media/Kids Movies/Toy Story 5 (2026)

Straight from the Barrio
/data/Media/Kids Movies/Straight from the Barrio (2008)
```

All checked records retained `hasFile=True`.

---

# 11. Sonarr migration results

Sonarr dry-run identified 23 series needing migration.

Examples:

```text
Silo
/media/TV Shows/Silo
-> /data/Media/TV Shows/Silo

Ragnarok
/media/TV Shows/Ragnarok
-> /data/Media/TV Shows/Ragnarok

Teach You a Lesson
/media/TV Shows/Teach You a Lesson
-> /data/Media/TV Shows/Teach You a Lesson
```

Apply was run.

Final dry-run:

```text
Mode: DRY-RUN
Would change: 0
Already migrated: 23
```

Sonarr series roots are now logically under:

`/data/Media/TV Shows/...`

---

# 12. Seerr root migration

Seerr desired roots were changed to:

```text
SONARR_ROOT = "/data/Media/TV Shows"
```

Radarr instances:

```text
/data/Media/Movies
/data/Media/Kids Movies
```

The associated tests in:

`tests/test_configure_seerr.py`

were updated.

Targeted Seerr tests passed.

Later, during live deployment validation on 2026-08-30, a Seerr-specific bug was found:

- `GET /settings/jellyfin/library` is not a read-only endpoint
- calling it without `enable=...` disables all Jellyfin libraries
- the original script used:
  - `GET /settings/jellyfin/library?sync=true` to inspect libraries
  - `GET /settings/jellyfin/library` to verify persistence
- this caused Seerr to accept the intended update and then immediately clear the enabled-library set during verification/summary

The fix was:

- read Jellyfin libraries from the safe settings endpoint:
  - `GET /settings/jellyfin`
- keep a single mutating call only for the real apply step:
  - `GET /settings/jellyfin/library?sync=true&enable=...`
- treat a mismatch in the apply response as an error instead of printing a warning and then issuing another destructive read
- update `print_summary()` to use `/settings/jellyfin`

After deploying the fixed script live, Seerr reported:

```text
Jellyfin libraries: Kids, Movies, Series
```

This resolved the persistence issue without touching qBittorrent, torrents, or storage paths.

---

# 13. Bazarr / Remote Path Mapping audit

Live Sonarr:
- zero Remote Path Mappings

Live Radarr:
- zero Remote Path Mappings

Bazarr audit:
- live container still has `/media`
- no `/media` or `/downloads` strings were found in Bazarr configuration files
- movie/series/episode/root-folder DB tables were empty when inspected
- Compose now also gives Bazarr `/data`
- `/media` remains for compatibility

Legacy mounts must remain for now.

---

# 14. qBittorrent original path design

Repo originally managed:

```text
movies -> /downloads/complete/movies
tv     -> /downloads/complete/tv
```

qBittorrent preferences originally used:

```text
save_path=/downloads
temp_path=/downloads/incomplete
```

Live category state before migration included:

```text
movies  -> /downloads/complete/movies
tv      -> /downloads/complete/tv
radarr  -> ""
prowlarr -> ""
```

Servarr download-client configuration:

Sonarr:

```text
tvCategory = 'tv'
```

Radarr:

```text
movieCategory = 'radarr'
```

This was initially suspicious because repo-managed qBittorrent category `movies` exists while Radarr itself uses `radarr`.

---

# 15. qBittorrent category-design resolution

The category design was investigated through Git history and live behavior.

Historical order:

`eabd3eb` / v0.7.0:
- Servarr settings management introduced
- Sonarr category = `tv`
- Radarr category = `radarr`

Later:

`0cd1c82` / v0.9.0:
- qBittorrent configuration-as-code introduced
- managed categories included `movies` and `tv`

Important behavior:

`scripts/configure-qbittorrent.py`
- creates/updates declared categories
- does not delete undeclared categories
- therefore `radarr` can legitimately remain as an additional live category

Live `radarr` category has empty explicit save path.

With Automatic Torrent Management and qBittorrent default path, new Radarr torrents resolve under:

```text
/data/Downloads/radarr
```

Therefore the design is intentional enough to preserve.

Do NOT change:

```text
Radarr movieCategory = radarr
```

to:

```text
movies
```

just to make names match.

The migration goal is storage namespace alignment, not category redesign.

---

# 16. qBittorrent desired new paths

Repo desired config now uses:

`stacks/media/qbittorrent/categories.json`

```json
[
  {
    "name": "movies",
    "save_path": "/data/Downloads/complete/movies"
  },
  {
    "name": "tv",
    "save_path": "/data/Downloads/complete/tv"
  }
]
```

`stacks/media/qbittorrent/preferences.json`

Relevant fields:

```json
{
  "save_path": "/data/Downloads",
  "temp_path_enabled": true,
  "temp_path": "/data/Downloads/incomplete",
  "auto_tmm_enabled": true,
  "torrent_changed_tmm_enabled": true,
  "save_path_changed_tmm_enabled": false,
  "category_changed_tmm_enabled": false
}
```

The desired qBittorrent config was applied successfully on 2026-08-30.

Final live state:

```text
movies -> /data/Downloads/complete/movies
tv     -> /data/Downloads/complete/tv
radarr -> ""
default path    -> /data/Downloads
incomplete path -> /data/Downloads/incomplete
```

Final dry-run reported:

```text
CATEGORY OK
PREFERENCES OK
```

Backups were created:

```text
/volume1/docker/media-stack/qbittorrent/categories.json.pre-data-migration-20260830
/volume1/docker/media-stack/qbittorrent/preferences.json.pre-data-migration-20260830
```

---

# 17. qBittorrent setLocation migration method

The migration method used for existing completed torrents is:

qBittorrent API:

`/api/v2/torrents/setLocation`

Because both:

```text
/downloads/...
/data/Downloads/...
```

are views of the same physical storage, setLocation changes qBittorrent's logical path rather than copying data.

Validation with Silo:

Old view:

```text
/downloads/complete/tv/Silo - S03E09 - Farewell HDTV-1080p.mkv
inode=3835
```

New view:

```text
/data/Downloads/complete/tv/Silo - S03E09 - Farewell HDTV-1080p.mkv
inode=3835
```

Same inode proved no duplication.

Observed qBittorrent behavior:
- `setLocation`
- torrent enters `checkingUP`
- qBittorrent rechecks data
- after verification:
  - `stalledUP`
  - or `uploading`
- `progress` during `checkingUP` is recheck progress
- it does NOT mean the file is being downloaded again

---

# 18. qBittorrent canary: The Time Traveler's Wife

Hash:

`4726c81040f00d3d4e3437b5da4c697d6165251b`

Before:

```text
save_path=/downloads/radarr
state=stalledUP
```

setLocation target:

```text
/data/Downloads/radarr
```

During recheck:

```text
state=checkingUP
progress advanced from ~2.9% to 77% etc.
```

After:

```text
state: stalledUP
progress: 100.0 %
save_path: /data/Downloads/radarr
content_path: /data/Downloads/radarr/The.Time.Travelers.Wife...
ratio: 0.9257115188133621
uploaded: 11612092968
```

Physical inode through both path aliases:

```text
inode=3827
```

This validated the migration method.

---

# 19. Completed public TV torrents migrated

These were migrated to:

`/data/Downloads/complete/tv`

Hashes:

```text
4b0b294f1eacf087f90870bbb753e6722716b852
ce1aab08e92ec9c86953d48197122816aa0c49f5
24a732f83f1b842e1709403f69348055f738b503
0c2991be74232ad70fd81600ee5fe8f15c24e325
3b2ac28347da5e4f5208522e6de43bd6287dc026
```

Corresponding episodes:

- Teach You a Lesson S01E02
- Teach You a Lesson S01E03
- Teach You a Lesson S01E05
- Teach You a Lesson S01E06
- Teach You a Lesson S01E07

They rechecked sequentially and all finished with:

```text
state=stalledUP
progress=100%
save_path=/data/Downloads/complete/tv
```

---

# 20. Private tracker: Milnueve — critical context

Milnueve is a PRIVATE tracker.

This matters because:
- private torrents have seeding obligations,
- deleting or stopping them too early can create Hit & Run violations,
- migration/cleanup logic must preserve their qBittorrent state and seeding timers.

The tracker was observed with a seeding requirement equivalent to:

```text
96 hours
```

qBittorrent per-torrent value:

```text
seeding_time_limit = 5760 minutes
```

5760 minutes = 96 hours.

Important Milnueve H&R understanding from prior investigation:
- if enough of the torrent is downloaded to count toward H&R (observed guidance: >=50%), seeding obligations apply
- required seeding time is 96 hours
- that requirement must be satisfied within the tracker's allowed H&R window (observed guidance: 14 days)
- stopping/deleting before the required seed time can create an H&R
- multiple H&Rs can lead to loss of download privileges
- previous notes indicated 5 H&Rs can be enough to lose download privileges

Important:
This tracker policy must be treated conservatively.
If in doubt, fail closed and keep seeding.

Do NOT:
- delete a private torrent before its finite positive seeding limit is satisfied
- reset seeding time
- remove torrent metadata
- force cleanup based only on file import status
- assume ratio alone satisfies the tracker unless explicitly verified
- assume freeleech/double-upload state is permanent

A Global Freeleech / Double Upload state was observed during earlier investigation.
Do NOT assume it remains active later.

Prowlarr/Cardigann configuration was observed with values including:

```text
minimumratio: 1.0
minimumseedtime: 1209600
```

1209600 seconds = 14 days.

Do NOT automatically equate that Cardigann `minimumseedtime` with the tracker's actual H&R requirement.
The tracker-side H&R behavior investigated separately indicated 96 hours of seeding within a 14-day window.

This distinction is important.

---

# 21. Private torrent migration validation

Three important private torrents were migrated and carefully validated.

## 21.1 Silo S03E09

Hash:

`77380929606ed0ef5b3a867ccfa1a8aa09efb532`

Before migration:
- private=True
- qBittorrent had a 5760-minute limit
- torrent was fully downloaded
- seeding counter already accumulated significant time

After setLocation and recheck:

```text
state: stalledUP
progress: 100.0 %
save_path: /data/Downloads/complete/tv
private: True
ratio: 0.053886580741267856
uploaded: 288945234
seeding_time: 66779
seeding_time_limit: 5760
```

The seeding timer did NOT reset.

## 21.2 Toy Story 5

Hash:

`2a494ff847206216d5469203d9ca20ab59fa5e8b`

After migration:

```text
state: stalledUP
progress: 100.0 %
save_path: /data/Downloads/radarr
private: True
ratio: 0
uploaded: 0
seeding_time: 68936
seeding_time_limit: 5760
```

Again, seeding time survived.

## 21.3 Talento de Barrio / Straight from the Barrio

Hash:

`c3f819f6a5644e56ec0a5607644bc393d325758a`

Before migration it was actively uploading.

After setLocation and recheck:

```text
state: stalledUP
progress: 100.0 %
save_path: /data/Downloads/radarr
private: True
ratio: 0.22335831243186705
uploaded: 518335797
seeding_time: 74008
seeding_time_limit: 5760
```

Seeding timer remained intact.

These successful migrations are important evidence that qBittorrent setLocation + recheck is safe for existing private torrents in this layout.

---

# 22. Force Start status

Force Start had previously been enabled for several downloads.

It was manually removed.

Reason:
- allow normal qBittorrent queueing,
- avoid bypassing configured limits,
- avoid complicating migration behavior.

Do NOT automatically re-enable Force Start.

---

# 23. Remaining old-path torrents

At the last detailed inventory, 11 torrents still used old `/downloads` paths.

These were intentionally left untouched because they were incomplete, queued, metadata-only, or stalled-downloading.

After applying the new qBittorrent default/category paths:
- these torrents retained old save paths,
- their progress/state remained intact,
- qBittorrent did not relocate them,
- they effectively remained pinned/manual due the configured relocation-policy settings.

Relevant preferences:

```text
save_path_changed_tmm_enabled=false
category_changed_tmm_enabled=false
```

Do not blindly migrate incomplete torrents.

They can safely finish through the compatibility `/downloads` mount.

Latest known list:

## 23.1 Sweet Magnolias S04E05

```text
hash: 00e658d5ab769046374ceb6d02a11e92cca18f63
category: tv
private: False
state: queuedDL
progress: 0.0%
save_path: /downloads/complete/tv
content_path: /downloads/incomplete/tv/...
```

## 23.2 Ragnarok S03E04

```text
hash: 96522a64e941d334321af44c596b211377377934
category: tv
private: False
state: stalledDL
progress: 99.8%
save_path: /downloads/complete/tv
content_path: /downloads/incomplete/tv/...
```

## 23.3 Bruid Van Die Jaar (2026)

```text
hash: d9ca37e145b70f341756d749a9444e42eb0425cd
category: radarr
private: None
state: queuedDL
progress: 0.0%
save_path: /downloads/radarr
content_path: empty
```

## 23.4 Teach You a Lesson S01E04

```text
hash: 44eede597c9e619e53c7d59b10527184114b903c
category: tv
private: False
state: queuedDL
progress: 0.0%
save_path: /downloads/complete/tv
```

## 23.5 Teach You a Lesson S01E08

```text
hash: e56bed73e19e33291dad7d6529cd7b6464ba2236
category: tv
private: False
state: queuedDL
progress: 86.5%
save_path: /downloads/complete/tv
```

## 23.6 Sweet Magnolias S04E03

```text
hash: 2a0b8acfb1cd9548f1a13f00a5b8fc006f72ff44
category: tv
private: False
state: queuedDL
progress: 0.0%
save_path: /downloads/complete/tv
```

## 23.7 Sweet Magnolias S04E08

```text
hash: 944be4f59aa453a8754e633298f4d724f5a0c82b
category: tv
private: False
state: queuedDL
progress: 0.0%
save_path: /downloads/complete/tv
```

## 23.8 Ragnarok S01E04

```text
hash: b706b58e6ff00a28890fd4b163555823518873fa
category: tv
private: False
state: stalledDL
progress: 86.27%
save_path: /downloads/complete/tv
```

## 23.9 Teach You a Lesson S01E09

```text
hash: b4f4a21ba2a57b49ab81b0b2aa83bcdd23a7bc75
category: tv
private: False
state: queuedDL
progress: 1.24%
save_path: /downloads/complete/tv
```

## 23.10 Ragnarok S01E03

```text
hash: 567e4b5e93fcfe986df51ef0754b89d409271985
category: tv
private: None
state: metaDL
progress: 0.0%
save_path: /downloads/complete/tv
content_path: empty
```

## 23.11 Teach You a Lesson S01E10

```text
hash: abc01378f9e3434106fdb728992a03bb344d482a
category: tv
private: False
state: queuedDL
progress: 0.0%
save_path: /downloads/complete/tv
```

Before acting on them, re-inventory their live states because some may have completed since the checkpoint.

---

# 24. Cleanup-safety review

Cleanup behavior is especially sensitive because of private tracker requirements.

Current review status:

- private torrents honor per-torrent seeding-time limits
- Milnueve private torrents with `seeding_time_limit=5760` must not be removed until the requirement is satisfied
- private torrents without a finite positive time limit fail closed
- private torrents with unknown/unbounded seeding policy should not be removed automatically
- Radarr cleanup was corrected to filter the actual `radarr` category instead of incorrectly using `movies`
- cleanup has NOT been executed live after these changes

This is intentional.

Destructive cleanup must not be tested live until:
- current torrent state is reviewed,
- private tracker protection is confirmed,
- required seeding time is satisfied,
- imported-file state is verified,
- path migration is stable.

---

# 25. Language-policy goal

Desired preference order:

```text
Latino > Castellano > English/original
```

This preference is intended to drive upgrades.

Examples:
- English -> Castellano is an upgrade
- Castellano -> Latino is an upgrade
- Latino -> Castellano is NOT an upgrade
- Unknown -> English is NOT considered sufficient for the custom language upgrader
- Unknown -> Castellano is allowed
- Unknown -> Latino is allowed

---

# 26. New language engine

New module:

`scripts/media/common/language.py`

Core ranking:

```python
class LanguageRank(IntEnum):
    UNKNOWN = 0
    ENGLISH = 1
    CASTILIAN = 2
    LATINO = 3
```

It centralizes:
- language detection,
- custom-format detection,
- title marker detection,
- upgrade ordering,
- sorting,
- safety rules.

Important rule added:

```text
candidate rank must be >= CASTILIAN
```

This prevents English from "upgrading" Unknown.

---

# 27. Latino helper refactor

`scripts/media/common/latino.py`

was refactored to use the shared language engine rather than duplicating detection logic.

It now calls:
- `language_rank`
- `LanguageRank.LATINO`

The module has dual import handling so it works:
- when run as part of deployed scripts with `common.language`
- and in repo unit tests via `scripts.media.common.language`

This fixed:

```text
ModuleNotFoundError: No module named 'common'
```

during local tests.

---

# 28. Sorting and approval semantics

There was an important regression while extracting the language engine.

The original Latino helper's `approval_sort_key` preferred:
- approved
- not rejected
- score
- seeders

A language-focused sort temporarily removed approval/rejection, causing tests to choose rejected releases.

This was corrected by separating concerns:

- legacy `approval_sort_key` still preserves usable-release preference
- language-upgrade sort ranks language first, then score/seeders
- safe language-upgrade filtering is done before sorting

Tests verified:
- usable release beats rejected release
- unrelated rejection is not overridden
- quality-only rejection can be overridden by explicit language-upgrade logic where intended

---

# 29. Language-title detection improvements

Initial title markers included generic short strings such as:

```text
SPA
ESP
```

Raw substring detection is dangerous because those sequences can appear inside unrelated words.

The later language-review work addressed this.

Current design concern/resolution:
- title matching should be token-aware
- explicit Latino title markers must take precedence over generic Spanish metadata
- generic Spanish matching must not accidentally classify a Latino-tagged release as Castellano
- `DUAL SPA ENG`-style releases need careful classification

The checkpoint notes indicate these concerns were addressed:
- token-aware matching
- explicit Latino marker precedence
- ambiguous dual-Spanish release handling

When reviewing the final diff, verify this remains true.

---

# 30. Spanish custom formats

Added:

```text
[Spanish] Castellano
[Spanish] Castellano + English
```

Both Sonarr and Radarr custom-format JSON files were updated.

Scores:

```text
[Latino] Spanish Latino             = 7000
[Latino] Spanish Latino + English   = 7000
[Spanish] Castellano                = 5000
[Spanish] Castellano + English      = 5000
[Latino] French Bonus               = 250
[Audio] Audio Description           = -10000
```

These scores produce the intended ordering:

```text
Latino > Castellano > unscored English/original
```

---

# 31. Castellano regex behavior

The custom formats detect Spanish/Castellano markers including examples such as:

```text
SPANISH
CASTELLANO
CASTILIAN
ESPANOL
ESPAÑOL
SPA
```

They also include exclusion rules for Latino markers.

Latino markers include patterns such as:

```text
LATINO
LATAM
ES-419 / ES.419 / ES 419
SPA-LAT
ESP-LAT
SPANISH-LATINO
AUDIO-LATINO
```

and some known release-group/user markers observed in the environment.

There was a concern that dual labels such as:

```text
DUAL SPA ENG
```

could simultaneously match Latino and Castellano depending on prior logic.

The later checkpoint says these ambiguous dual markers were excluded from Castellano scoring.

When finalizing, inspect the JSON regexes carefully.

---

# 32. Recyclarr changes

`stacks/media/recyclarr/recyclarr.yml`

was updated so custom-format deletions/exclusions preserve custom formats whose names begin with:

```text
^[Latino]
^[Spanish]
^[Audio]
```

This prevents Recyclarr from deleting managed custom formats in those namespaces.

---

# 33. Radarr language policy

`scripts/configure-radarr-policy.py`

was changed from:

```text
LANGUAGE_NAME = "Original"
```

to:

```text
LANGUAGE_NAME = "Any"
```

Reason:

The preference is now implemented using custom-format scoring:

```text
Latino > Castellano > English/original
```

Radarr must not reject Spanish candidates at the language-profile level before scoring can apply.

Dry-run showed:

```text
WOULD UPDATE RADARR PROFILE
language: Original -> Any
```

Apply succeeded:

```text
UPDATED RADARR PROFILE
language: Original -> Any
```

Live verification:

```text
RADARR language: {'id': -1, 'name': 'Any'}
```

---

# 34. Servarr custom-format deployment

After repo changes, local files were copied to NAS for live validation.

New custom formats were created live.

Sonarr:
```text
[Spanish] Castellano
[Spanish] Castellano + English
```

Radarr:
```text
[Spanish] Castellano
[Spanish] Castellano + English
```

Scores live:

```text
Latino formats: 7000
Castellano formats: 5000
French Bonus: 250
Audio Description: -10000
```

Profile:
`Latino 1080p`

---

# 35. Real release validation: Silo S03E09

Existing Sonarr file:

```text
Path:
/media/TV Shows/Silo/Season 3/Silo - S03E09 - Farewell WEBDL-1080p.mkv

Languages:
English
Turkish
German
French

Quality:
WEBDL-1080p

Score:
75

Formats:
ATVP
```

Milnueve candidate:

```text
Silo - S03E09 - Farewell HDTV-1080p.mkv Spanish
```

Candidate details:

```text
Languages:
Spanish

Quality:
HDTV-1080p

Score:
5000

Formats:
[Spanish] Castellano
Language: Not Original

Seeders:
~33

DownloadAllowed:
True
```

Sonarr itself rejected it because:

```text
Existing file on disk is of equal or higher preference: WEBDL-1080p v1
```

This was the exact real-world case motivating explicit language-first upgrade logic.

---

# 36. Sonarr language-upgrade script

`scripts/media/upgrade-sonarr-latino.py`

was changed from Latino-only behavior toward general language-ranking behavior.

It now uses:
- installed language rank
- best safe language upgrade
- language names in output

Example dry-run result:

```text
WOULD GRAB: S03E09 english -> castilian score=5000 seeders=33
Silo - S03E09 - Farewell HDTV-1080p.mkv Spanish
```

It also gained:

```text
--episode
```

with validation:
- `--episode` requires `--series`
- `--episode` requires `--season`

Example:

```bash
sudo python3 scripts/upgrade-sonarr-latino.py \
  --series "Silo" \
  --season 3 \
  --episode 9 \
  --dry-run
```

---

# 37. Radarr language-upgrade script

`scripts/media/upgrade-radarr-latino.py`

was also migrated to language-ranking logic.

It no longer hardcodes:
- Latino-only custom format checks
- fixed 7000 threshold
- score-only upgrade comparison

It now uses:

```text
best_language_upgrade
language_name
```

Real dry-run against:

`Resident Evil: Death Island`

returned:

```text
language: english -> castilian
current score: 0
candidate score: 5000
quality: HDTV-1080p
release: Resident Evil - Death Island (2023) 1080p DTS.mkv Spanish
```

This proved the new policy works on a real Milnueve result.

---

# 38. ArrClient POST bug

Shared module:

`scripts/media/common/arr.py`

provides:

```text
request()
get()
delete()
```

It does NOT provide:

```text
post()
```

The upgrade scripts originally called:

```python
client.post(...)
```

This failed live with:

```text
AttributeError: 'ArrClient' object has no attribute 'post'
```

Both Sonarr and Radarr upgrade scripts were fixed to use:

```python
client.request("POST", ...)
```

Do not reintroduce `.post()` calls unless ArrClient is intentionally extended.

---

# 39. Silo download and import

After fixing the Sonarr API call, the Silo S03E09 Castellano candidate was grabbed.

qBittorrent showed:

```text
state: downloading
progress advanced to 100%
private: True
tracker: Milnueve
seeding_time_limit: 5760
```

After completion:

```text
state: stalledUP
progress: 100%
```

However, Sonarr did NOT automatically import it because the technical quality was lower:

```text
Existing quality: WEBDL-1080p
New quality: HDTV-1080p
```

Sonarr queue:

```text
status: completed
trackedDownloadStatus: warning
trackedDownloadState: importPending

status message:
Not an upgrade for existing episode file(s).
Existing quality: WEBDL-1080p.
New Quality HDTV-1080p.
```

---

# 40. Sonarr ManualImport API investigation

`GET /api/v3/manualimport` returned the candidate and rejection.

`POST /api/v3/manualimport` was discovered to exist, but posting a payload only returned evaluation data and did not force the import.

The successful mechanism was Sonarr command endpoint:

`POST /api/v3/command`

with:

```text
name: ManualImport
```

and file metadata including:
- path
- seriesId
- episodeIds
- quality
- languages
- releaseType
- downloadId
- indexerFlags

Command ID:

`76962`

Final command status:

```text
status: completed
result: successful
message: Manually imported 1 files
```

After import:

```text
Episode file ID: 223
Path: ...Silo - S03E09 - Farewell HDTV-1080p.mkv
Languages:
Spanish
English
Quality:
HDTV-1080p
```

This is a real proof that lower technical quality can be intentionally imported when language preference is higher.

---

# 41. Silo physical import before hardlink migration

At the time of the manual Silo import, host stat showed:

Downloads copy:

```text
inode=3835
links=1
size=5358272425
```

Library copy:

```text
inode=3836
links=1
size=5358272425
```

Different inodes proved Sonarr copied the file rather than hardlinking.

That observation directly triggered the `/data` hardlink migration.

---

# 42. Final end-to-end hardlink proof

The critical proof was completed with a NEW real Sonarr import after the
`/data` architecture and qBittorrent desired paths were active.

Test content:

```text
Reacher S04E05 - Bridge
Public 1337x release
Reacher.S04E05.720p.x264-FENiX
qBittorrent hash: da2d4a167aeace92ef6703ab7407b5bac94f5d45
```

qBittorrent created the torrent with:

```text
category=tv
auto_tmm=True
force_start=False
save_path=/data/Downloads/complete/tv
incomplete path=/data/Downloads/incomplete/tv/...
```

It completed normally and Sonarr imported it automatically with no queue
warning.

Download file:

```text
/volume1/Family/Downloads/complete/tv/Reacher.S04E05.720p.x264-FENiX/Reacher.S04E05.720p.x264-FENiX.mkv
```

Library file:

```text
/volume1/Family/Media/TV Shows/Reacher/Season 4/Reacher - S04E05 - Bridge HDTV-720p.mkv
```

Final host stat:

```text
inode=3873 links=2 device=70 size=693813263 path=/volume1/Family/Downloads/complete/tv/Reacher.S04E05.720p.x264-FENiX/Reacher.S04E05.720p.x264-FENiX.mkv
inode=3873 links=2 device=70 size=693813263 path=/volume1/Family/Media/TV Shows/Reacher/Season 4/Reacher - S04E05 - Bridge HDTV-720p.mkv
```

This proves end-to-end that:
- qBittorrent creates new downloads under `/data/Downloads`
- Sonarr imports through `/data/Media`
- the import is a hardlink
- the download and library paths share one inode
- qBittorrent can continue seeding without a duplicate media copy

The generic validation procedure remains:

For a newly completed torrent:

Download file:

```text
/data/Downloads/...
```

Library file:

```text
/data/Media/...
```

Run:

```bash
stat -c "inode=%i links=%h size=%s path=%n" \
  "<download-file>" \
  "<library-file>"
```

Expected:

```text
same inode
links >= 2
same size
```

This is the definitive end-to-end validation that:
- qBittorrent downloads through `/data`
- Sonarr/Radarr import through `/data`
- hardlinks are used
- no duplicate storage is consumed
- qBittorrent can continue seeding while Jellyfin sees the library file

Compatibility mounts still remain because legacy incomplete torrents and
Jellyfin continue to use them. Their removal remains a separate later change.

---

# 43. README status

`stacks/media/README.md`

was initially stale and documented:

```text
movies -> /downloads/complete/movies
tv     -> /downloads/complete/tv
```

Later checkpoint says README was updated to document:
- final `/data/Downloads/...` paths
- why Radarr continues to use separate `radarr` category

Verify the final diff reflects this.

---

# 44. deploy.sh considerations

The new shared module:

`scripts/media/common/language.py`

must be deployed to NAS together with other shared media modules.

Earlier `scripts/deploy.sh` only explicitly handled:
- `__init__.py`
- `arr.py`
- `qbittorrent.py`
- `cleanup.py`
- `latino.py`

Later checkpoint says:
- `scripts/deploy.sh` now installs `scripts/common/language.py`

Verify deployment paths carefully.

The deployed runtime path used by media scripts is:

```text
/volume1/docker/media-stack/scripts/common/language.py
```

Make sure final deploy logic includes this file and cleans temporary staging correctly.

---

# 45. Security / secrets

Never commit:
- qBittorrent password
- qBittorrent credentials JSON
- Sonarr API keys
- Radarr API keys
- Prowlarr API keys
- Milnueve API key
- Milnueve passkey
- private tracker announce URLs containing passkeys
- NAS-local private-indexer secret files

Known NAS-local private indexer secret:

```text
/volume1/docker/media-stack/secrets/prowlarr-private-indexers.json
```

Example file in repo:

```text
stacks/media/secrets/prowlarr-private-indexers.example.json
```

Real credentials must remain NAS-local.

Before commit:

```bash
git diff
git status --short
```

Search for obvious secret patterns if needed.

---

# 46. SSH warning

SSH sessions to NAS have repeatedly shown:

```text
WARNING: connection is not using a post-quantum key exchange algorithm.
This session may be vulnerable to "store now, decrypt later" attacks.
```

This is unrelated to the media-stack migration itself.

Do not treat it as a migration failure.

It may be addressed separately by upgrading/configuring the SSH server/client later.

---

# 47. Known qBittorrent states encountered

Relevant state meanings in this migration:

```text
checkingUP
```
- qBittorrent is verifying completed data
- progress field is check progress
- not a redownload

```text
stalledUP
```
- completed
- available for seeding
- currently no active upload peer

```text
uploading
```
- actively seeding/uploading

```text
stalledDL
```
- incomplete
- no current download progress / peers

```text
queuedDL
```
- queued for download

```text
metaDL
forcedMetaDL
```
- fetching metadata

```text
downloading
forcedDL
```
- actively downloading
- force variants bypass normal queue behavior

Force Start was removed manually.

---

# 48. Private-tracker cleanup principle

For a private torrent:

If:
- it is complete,
- media has been imported,
- qBittorrent says it is private,

cleanup must still check:

```text
seeding_time_limit
seeding_time
```

If the limit is finite and positive:

```text
seeding_time < seeding_time_limit * 60
```

then cleanup must NOT delete it.

If private torrent has no finite positive limit:
- fail closed
- keep torrent
- do not assume safe deletion

If tracker policy is ambiguous:
- keep torrent
- require human review

This policy is more important than reclaiming space.

Hardlinks reduce pressure to delete seeded downloads anyway.

---

# 49. Why hardlinks matter for private trackers

With copies:

```text
Downloads file: 10 GB
Library file:   10 GB
Total physical: ~20 GB
```

With hardlinks:

```text
Downloads path -> inode X
Library path   -> inode X
Total physical: ~10 GB
```

This means qBittorrent can keep the torrent for 96h+ seeding obligations without doubling disk usage.

This is a major reason the storage migration is worth completing.

---

# 50. Final intended architecture

```text
                         Seerr
                           |
                  requests media
                           |
               +-----------+-----------+
               |                       |
             Sonarr                  Radarr
               |                       |
               +-----------+-----------+
                           |
                      qBittorrent
                           |
                           v
                 /data/Downloads
                  / incomplete
                  / complete/tv
                  / complete/movies
                  / radarr
                           |
                  completed media
                           |
                 hardlink import
                           |
          +----------------+----------------+
          |                                 |
/data/Media/TV Shows              /data/Media/Movies
                                  /data/Media/Kids Movies
          |                                 |
          +----------------+----------------+
                           |
                        Jellyfin
```

Important:
- qBittorrent download paths and final media library remain logically separate
- `/data` only unifies the mount namespace
- this does NOT mean downloading directly into Media
- Sonarr/Radarr still own import/rename/library placement
- qBittorrent still owns the original torrent data

---

# 51. What should NOT be done

Do NOT:
- remove `/downloads` compatibility mount yet
- remove `/media` compatibility mount yet
- move all incomplete torrents at once
- change Radarr category `radarr` to `movies`
- turn the migration into a category redesign
- re-enable Force Start globally
- interpret `checkingUP` as redownload
- delete private torrents before seed requirements
- run cleanup live without review
- use `configure-radarr.py` for alias migration
- use `moveFiles=true` for `/media` -> `/data/Media`
- reset Sonarr/Radarr DBs
- rebuild qBittorrent state
- discard the active Git diff
- commit secrets
- remove NAS backups before final validation

---

# 52. Recommended safe continuation order

1. Read this file fully.

2. Confirm Git branch and state:

```bash
git branch --show-current
git status --short
git diff --check
git diff --stat
```

3. Run tests:

```bash
make check
```

4. Re-inventory qBittorrent:
- identify remaining torrents still on `/downloads`
- note whether any have now completed
- do not act based on stale states from this document

5. For each newly completed old-path torrent:
- verify private/public status
- if private, record:
  - ratio
  - uploaded
  - seeding_time
  - seeding_time_limit
- migrate with setLocation only if safe
- allow recheck
- verify `progress=100`
- verify state returns to `stalledUP`/`uploading`
- verify counters preserved

6. Leave incomplete torrents on compatibility `/downloads` until complete unless there is a specific reason to move them.

7. A NEW Sonarr download under `/data` was completed successfully.

8. Its `/data/Media` import path was validated.

9. Hardlink E2E validation passed: inode 3873, links=2, same size.

10. Review Sonarr/Radarr queue for any import warnings.

11. Review qBittorrent category behavior for new Sonarr and Radarr downloads:
- Sonarr -> `tv`
- Radarr -> `radarr`
- expected save paths under `/data/Downloads`

12. Review cleanup scripts in dry-run only.

13. Review private tracker protection.

14. Verify deploy.sh includes language.py.

15. Review README.

16. Review Bazarr/Jellyfin compatibility.

17. Only after all consumers are proven safe, plan a separate cleanup PR/change to remove legacy mounts.

18. Final tests:

```bash
make check
git diff --check
```

19. Review full diff:

```bash
git diff
git status --short
```

20. Check for secrets.

21. Commit only after human review.

---

# 53. Suggested Codex startup prompt

Use this when opening the repo in Codex:

```text
We are continuing an in-progress homelab media-stack change.

Repository:
~/home-labs/homelab

Before making ANY changes, read this entire file:

docs/HOMELAB_MEDIA_CONTEXT.md

Treat it as the canonical handoff/checkpoint.

Current branch should be:
feat/spanish-language-upgrades

Do not reset, restore, stash, discard, checkout another branch, or overwrite existing work.

The work has two goals:

1. Language preference:
   Latino > Castellano > English/original

2. Storage migration:
   move the container namespace from separate /downloads and /media mounts
   toward a shared /data parent mount so Sonarr/Radarr can hardlink
   /data/Downloads files into /data/Media while qBittorrent continues seeding.

Important:
- Sonarr and Radarr library paths are already migrated to /data/Media.
- qBittorrent /data mount is active.
- qBittorrent desired configuration for new downloads has been applied.
- several completed torrents, including private Milnueve torrents, were already migrated successfully.
- private tracker seeding timers must be preserved.
- legacy /downloads and /media mounts must remain for now.
- remaining incomplete old-path torrents must not be blindly migrated.
- Radarr intentionally uses category `radarr`; do not rename it to `movies`.
- cleanup must fail closed for private torrents when seeding requirements are not clearly satisfied.
- the final critical validation still needed is a NEW real Sonarr/Radarr import proving download and library files share the same inode with link count >= 2.

First:
1. read docs/HOMELAB_MEDIA_CONTEXT.md fully,
2. run git branch --show-current,
3. run git status --short,
4. run git diff --check,
5. run make check,
6. inspect the current diff,
7. report current repository state and safest next action before making any destructive live NAS change.
```

---

# 54. Key invariant

The migration is NOT intended to reorganize the media stack.

It is intended to preserve the existing logical flow while changing the container namespace so:

```text
/data/Downloads
/data/Media
```

share a single mount boundary.

Preserve:
- qBittorrent download ownership
- Sonarr/Radarr import ownership
- Jellyfin library consumption
- private tracker seeding
- category semantics
- existing media paths on disk

Change only what is required to enable hardlinks and language preference.

---

# 55. Final desired success criteria

The work is complete only when all of the following are true:

- `make check` passes
- `git diff --check` passes
- no secrets are in Git diff
- Radarr accepts `Any` language
- custom-format scoring reflects:
  Latino > Castellano > English/original
- language upgrade scripts behave safely
- explicit Latino does not get downgraded to Castellano
- English does not upgrade Unknown
- deployment includes `language.py`
- Sonarr/Radarr roots are `/data/Media/...`
- qBittorrent new downloads use `/data/Downloads/...`
- existing private torrents retain seed counters and limits
- cleanup cannot violate private tracker obligations
- a NEW real import is confirmed as a hardlink:
  same inode, links >=2
- no active consumer requires old paths before compatibility mounts are removed
- README reflects final path behavior
- compatibility mount removal, if desired, happens only as a separate later cleanup

---

# 56. Seerr browser link correction

On 2026-09-01, `Play on Jellyfin` was found to use the Docker-only URL
`http://jellyfin:8096/...`, which fails in LAN browsers with
`ERR_NAME_NOT_RESOLVED`. The repository now manages Seerr's
`externalHostname` dynamically from the NAS mDNS hostname and Jellyfin's
published Docker port, while preserving the internal Docker endpoint
`jellyfin:8096` for Seerr-to-Jellyfin API traffic.

`DH4300PLUS-9186.local` was verified from macOS as browser-reachable. Live
deployment and `make audit-seerr` confirmed the external URL persisted, the
internal endpoint remains unchanged, and Jellyfin libraries plus Servarr
routing are healthy. The next configuration run automatically adapts if the
NAS hostname or published Jellyfin port changes.

---

# 57. Follow-up audit: Powerpuff, Seerr, and legacy mounts (2026-09-01)

The stack was re-audited after the RetroToon Powerpuff import and Seerr
browser-link fix.

Validated live:

- all Compose services answered their health checks
- Bazarr had no `/downloads`, `/media`, or `/data` references in its stored
  configuration; its `/media` mount remains compatibility-only
- Seerr request `37` maps by TVDB identity to Sonarr series `31` at
  `/data/Media/TV Shows/The Powerpuff Girls`
- Sonarr reports 49 library episodes for that request and recent files have
  verified qBittorrent-to-library hardlinks (same inode, link count `2`)
- all four private torrents remain protected by the tracker audit; the
  RetroToon torrent is still within its 72-hour requirement and the three
  Milnueve torrents retain their configured 5760-minute obligations

The RetroToon Powerpuff package was inspected. Its media files contain a
Spanish (`spa`, titled `Español Latino`) stream plus English, but its episode
layout is incomplete and mixes alternate numbering. The guarded title-matched
import correctly created only 49 unambiguous hardlinks. Do not fabricate
Sonarr season/episode mappings for the remaining files; source material for
Sonarr's season 3 is not present and several remaining files are
multi-episode or localized-title releases.

`make audit-legacy-mounts` is now the canonical read-only pre-removal audit.
The latest inventory found seven public qBittorrent torrents still using
`/downloads`; all are incomplete, metadata-only, or stalled downloads. A
previous completed and imported public torrent was removed automatically after
its 30-minute retention period. Consequently `/downloads` and `/media` must
remain mounted. Root folders themselves are correct:

```text
Sonarr: /data/Media/TV Shows
Radarr: /data/Media/Movies
        /data/Media/Kids Movies
```

The Silo S03E09 Milnueve release is already imported and still seeding. Sonarr
may retry its same RSS result because the imported file's historical custom
format score differs from the release score. Do not use Sonarr's generic
"mark as failed" endpoint without an explicit, tracker-safe confirmation: it
may invoke failed-download handling and its effect on the protected torrent
was not proven. Keep the qBittorrent torrent unchanged while the private
tracker requirement is outstanding.

New commands:

```bash
make audit-legacy-mounts
make audit-seerr-request-flow REQUEST_ID=37
```

`make verify-hardlinks` accepts either the host paths under
`/volume1/Family/...` or the container namespace under `/data/...`.

---

# 58. Torrent Haven native Prowlarr integration (2026-09-02)

Torrent Haven (`torrenthaven.org`) was added as Prowlarr indexer `ID=9` using
the native `torrenthaven-api` Cardigann definition. Its API token is stored
only in the NAS-local private-indexer secret and must never be committed or
logged.

Managed policy:

- priority `9`; minimum seeders `1`
- 72-hour (`4320` minute) seed time for both normal releases and packs
- no ratio-based early stop, despite the tracker allowing either 1:1 or 72 h
- private-tracker audit recognizes `torrenthaven.org` and requires at least
  4320 minutes

The tracker rules also prohibit DHT, PEX, and additional tracker URLs for
Torrent Haven torrents. qBittorrent currently keeps discovery enabled
globally for public torrents; do not change those global defaults without
  first validating that Torrent Haven's downloaded `.torrent` is private and
  that qBittorrent suppresses discovery for it.

---

# 59. Torrent Haven movie end-to-end proof (2026-09-03)

A Seerr request for TMDB `953` (Madagascar, 2005) was used to exercise the
movie workflow while retaining the request record. Radarr initially selected a
public fallback; it was explicitly marked failed, its qBittorrent payload was
removed, and the public imported file was removed from Radarr before the
private selection was allowed to import.

The guarded `grab-prowlarr-release` helper now supports both media types:

- TV: exact title + TVDB ID validation
- movie: exact title + TMDB ID validation, `MEDIA_TYPE=movie`, and the
  `radarr` qBittorrent category

The selected Torrent Haven torrent was verified after completion as follows:

- `private=true`; tracker hosts: only `torrenthaven.org`
- tags include `private` and `torrenthaven`; seed-time limit `4320` minutes
- qBittorrent state is seeding/stalled-up after completion, rather than being
  eligible for public-torrent cleanup
- Radarr imported it using a hardlink: download and library file have the same
  inode and a link count of `2`
- MediaInfo reports only English audio. Despite `1080p` in the release name,
  the actual video is 960x540 and Radarr classifies it as `WEBDL-480p`.

Conclusion: identity, tracker privacy, seeding protection, Arr import, and
hardlink behavior are all proven. Release names are not trusted as a quality
or language claim; use Radarr/Sonarr's resulting MediaInfo-derived fields as
the source of truth.

The resulting policy is intentionally strict for future automatic private
grabs: require Castilian-or-Latino and a title claim of at least 720p. English
is only an explicit fallback. This keeps private priority from overriding the
repository's Spanish-first behavior while still allowing a chosen private
torrent to seed until its tracker requirement is satisfied.

The policy was deployed and tested with a dry-run of the same Madagascar
Torrent Haven result. The helper rejected it before contacting qBittorrent:
the Prowlarr result did not prove a Castilian-or-Latino language, despite its
`1080p` title claim. This is expected: title resolution is only a preliminary
gate; post-import MediaInfo remains authoritative.

---

# 60. Scheduled private Seerr candidate evaluation (2026-09-03)

`dispatch-private-seerr.py` evaluates outstanding Seerr movie requests across
Milnueve, RetroToon, and Torrent Haven. It requires exact TMDB identity, at
least one seeder, and `private-release-policy.json`; tracker priority is only a
tie-breaker after that policy has accepted the release.

The installed `media-stack-private-dispatch.timer` runs every 30 minutes in
preview mode. It never adds a torrent or changes a Seerr request. This produces
scheduled evidence without risking a silent quality/language regression.

`make dispatch-private-seerr` runs that preview on demand. The guarded,
explicit apply command is `APPLY=1 make dispatch-private-seerr`; it adds a
private qBittorrent tag plus a unique `seerr-request-<id>` tag and refuses to
dispatch the same request twice. Keep automatic application disabled until a
real policy-compliant candidate has completed the exact same path and its Arr
import/hardlink outcome is verified.

---

# 61. Automated retention after private tracker compliance (2026-09-04)

The 15-minute imported-torrent retention service now covers both public and
managed private torrents. Public torrents still require a confirmed Arr import
and 30 minutes of seeding. A private torrent additionally requires all of:

- qBittorrent explicitly reports it as private;
- its tracker host matches a managed policy;
- it has a finite positive qBittorrent seed limit;
- its measured seeding time has reached the greater of that limit and the
  tracker policy; and
- Sonarr or Radarr has confirmed its import.

Any unknown, unbounded, incomplete, Force Start, pending, or unimported private
torrent fails closed and remains in qBittorrent. This turns completed tracker
obligations into automated cleanup without risking an H&R or premature payload
deletion.

The title-matched Sonarr helper is a special safe case: it creates library
hardlinks directly and uses a rescan, so it lacks a normal qBittorrent
download-id import-history record. The retention job recognizes this only when
it can verify a real inode match between the private download and a file under
the media library.

Validation: the completed RetroToon `Las Supernenas (1992)` package contained
Spanish-Latin and English tracks in its normally named seasons. Forty-nine
unambiguous episodes were already present as verified hardlinks in Sonarr's
library; twenty-seven irregular/localized files remained intentionally outside
the automated mapping. After 4,321 minutes of seeding, the scheduled retention
job verified that evidence and removed the completed qBittorrent payload while
leaving the library hardlinks intact.
