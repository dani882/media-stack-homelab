# Media Stack Working Memory

This repository manages the user's media stack on `ugreen-nas`. Treat this
file as durable project context for future Codex sessions. Never copy tracker
credentials, API keys, passkeys, cookies, or account identifiers into the
repository, terminal output, documentation, commits, or chat responses.

## User intent and communication

- Communicate with the user in clear, non-technical Spanish.
- The user wants automated media selection in this order:
  `Latino > Castellano > English/original`.
- Language always outranks source quality and tracker priority. A private or
  high-priority tracker must never cause Spanish audio to be replaced by
  English-only content.
- Tracker priority breaks ties only after language and acceptable quality.
- Preserve older private torrents until their tracker-specific seeding or
  ratio obligation is satisfied, even after a better file is imported into
  the library.

## Stack and paths

- Flow: Seerr -> Radarr/Sonarr -> Prowlarr -> qBittorrent -> Jellyfin.
- NAS stack directory: `/volume1/docker/media-stack`.
- Family data root: `/volume1/Family`, mounted as `/data` in Arr containers.
- Downloads: `/volume1/Family/Downloads`.
- Movie library: `/volume1/Family/Media/Movies`.
- Series library: `/volume1/Family/Media/TV Shows`.
- Arr imports use hardlinks when possible. Files in `Downloads` remain for
  seeding without consuming a second copy of the media data.
- Private-indexer credentials live only in the NAS-local secrets file. Use
  existing deployment/configuration scripts; never print the secret file.

## Tracker priority and retention

- Lat-Team priority 1 is reserved for a future account and is not active.
- BTArg is priority 2 and is the first active Latin-oriented tracker.
- Milnueve is priority 4 with a 106-hour seed-time policy.
- RetroToon World is priority 8 with an 82-hour seed-time policy.
- DreadVault and TorrentHaven are priority 9; DreadVault uses 130 hours and
  TorrentHaven uses 82 hours.
- Public indexers are interactive/manual fallback only: RSS and automatic
  search are disabled for them.
- Prowlarr queries indexers concurrently. Its numeric priority is only a
  release-selection tiebreaker; it is not a sequential search order.

## BTArg policy

- BTArg uses Prowlarr's native username/password definition; it has no API
  token field.
- BTArg is private, but not every release is Latino. Unmarked or English-only
  BTArg releases are ordinary English fallback, not preferred-language media.
- Configure BTArg with minimum 1 seeder and per-torrent ratio target 1.0.
- BTArg's site rules include a minimum account ratio of 0.5, at most 6
  simultaneous downloads and 8 uploads, and Hit & Run enforcement without a
  fixed published seed time. Prefer 1:1 as the conservative release target.
- BTArg currently announces through `announce.btarg.org`.
- Do not add extra trackers to private torrents.

## Language-first implementation

- Managed profiles use one quality group named
  `HD 720p-1080p (Language First)` so language custom-format scores compare
  before HDTV/WEB-DL/BluRay or 720p/1080p differences.
- Persistent custom formats `LATINO` and `CASTELLANO` are included in managed
  Arr filenames. This prevents language scores from disappearing after Arr
  renames an imported release.
- Audio-metadata guards protect existing files that contain Spanish or Latino
  audio even when they predate the persistent filename markers.
- Legacy verbose language formats have score 0 to avoid double-counting. The
  persistent marker plus audio guard must remain below the magnitude of hard
  rejection scores such as x265/AV1 `-10000`; language preference must not
  make an explicitly banned technical format eligible.
- Explicit adjacent markers such as `Spa SubS` or `Spanish Subs` are
  subtitle-only indicators and must not be treated as Spanish audio.
- Bare `Dual Audio` is ambiguous. Do not globally classify it as Latino. It
  may be selected only when an explicit language marker, reliable Arr
  metadata, or manual tracker-detail verification establishes the audio.
- `scripts/media/common/language.py` is the shared ranking source for audits
  and explicit upgrade helpers.
- `scripts/deploy-language-priority.sh` deploys the focused language policy.

## Private-torrent replacement safety

- Replacing a library file does not authorize deleting its original torrent.
- Keep all incomplete-obligation private torrents in qBittorrent and allow
  them to seed after their library hardlink is replaced.
- `scripts/audit-private-trackers.py` enforces time- or ratio-based policies.
- `scripts/cleanup-public-imported.py` must refuse private cleanup until the
  configured seed time or finite ratio is satisfied.
- Public partial downloads may be removed and blocklisted when the user asks
  to replace them with a verified private release.

## Verified examples (2026-09-09)

- `A Minecraft Movie (2025)` was removed as a partial public download and
  replaced with a private BTArg WEB-DL. BTArg site details were manually
  verified as Spanish Latino + English because the release title only said
  `Dual Audio`. The BTArg torrent remains protected to ratio 1.0.
- `Silo S03E09` from BTArg was English-only and incorrectly replaced a
  Spanish+English Milnueve HDTV file. The language-first policy was corrected,
  and the Milnueve file was restored to the library as
  `Silo - S03E09 - Farewell [CASTELLANO] HDTV-1080p.mkv` with real audio
  metadata `spa/eng`. Both the BTArg and Milnueve torrents remain for seeding.
- Do not delete the Milnueve Silo torrent before its 106-hour requirement.
- A full monitored-library audit found no safe private-language upgrade for
  `The Last of Us`, `Silo`, or `Ranma ½`. Public results and x265 results were
  correctly excluded. `Resident Evil: Death Island (2023)` was the sole safe
  private upgrade and was grabbed from Milnueve as Castellano; verify its
  final imported audio after the download completes.

## Operational workflow

- For monitored-library language upgrades, always run the Sonarr and Radarr
  upgrade helpers with `--dry-run` first, inspect every proposed release, then
  run without `--dry-run` only for safe language improvements.
- Automatic monitored-library upgrades are limited to the known private
  indexers. Public interactive results remain manual fallback and must never be
  grabbed by the batch upgrade helpers.
- Slow release searches retry once. If a title still times out, it is skipped
  and the rest of the audit continues; revisit skipped items separately.
- Validate changes with `python3 -m unittest discover -s tests`,
  `git diff --check`, and relevant live read-only audits before committing.
- Keep deployment scripts scoped and idempotent. Avoid full-stack restarts for
  tracker or language-policy-only changes.
