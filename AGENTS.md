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
- Treat unmistakable YTS/YIFY payload names as English-first even when a
  tracker detail page claims Spanish audio. Inspect torrent members while
  paused and reject that conflict before downloading.
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

## Verified examples (2026-09-11)

- A BTArg detail page incorrectly described an `Enola Holmes 3 (2026)` YTS
  payload as Castellano. The downloaded file had one untagged audio stream,
  and a speech sample was confirmed as English. Its Radarr library file was
  removed, while the private torrent was retained for ratio 1.0 and tagged
  `language-mismatch`. Guarded grabs now reject Spanish claims that conflict
  with unmistakable YTS/YIFY torrent member names before downloading.
- Eight long-stalled public downloads were removed and blocklisted through
  their Arr queue entries. Seven monitored items received fresh searches;
  the unmonitored `La Brea S01E01` was intentionally not searched.

## Operational workflow

- `media-stack-btarg-series.timer` handles BTArg multi-season TV packs that
  Sonarr rejects natively. It only accepts exact requested-season coverage,
  an IMDb identity match, at least one seeder, safe payload extensions, and
  explicit Latino audio from the authenticated BTArg detail page. It downloads
  at most one new pack per run, preserves the torrent to ratio 1.0, maps
  broadcast-segment files to Sonarr episodes by title, converts HEVC to H.264,
  and imports only missing episodes with a persistent `[LATINO]` marker.
- Do not treat this importer as permission to replace existing episode files.
  Existing Spanish, Latino, or English files remain untouched by this flow.
- BTArg language classification is shared through
  `scripts/media/common/btarg.py`. Authenticated detail results contain no
  credentials and are cached for seven days; unknown results expire after six
  hours. Searches with no safe pack back off for 6, 12, then 24 hours.
- The BTArg pack worker must reserve enough free space for the download plus a
  possible H.264 conversion, run only one conversion worker, and verify the
  resulting Sonarr episode-file association before applying the
  `btarg-import-verified` tag.
- BTArg HEVC imports prefer the NAS Rockchip `h264_rkmpp` encoder after a
  short capability test. Every generated file is probed before import, and a
  hardware failure automatically retries that file with `libx264`; do not
  remove this software fallback.
- BTArg conversions write deterministic temporary files under
  `/volume1/Family/Downloads/.transcode/btarg-series`, never in the media
  library. Before final placement, verify codec, dimensions, duration, audio
  and subtitle counts, audio-language tags, and decodability at the end.
- Rescan Sonarr after each completed season so finished seasons become visible
  while a large pack continues. Progress, ETA, encoder speed, hardware
  temperature, and fallback count are written without secrets to
  `state/btarg-series-progress.json` and `.html`. Pause a conversion rather
  than start hardware encoding at 85 C or higher.
- `media-stack-language-repair-audit.timer` creates a daily dry-run report for
  monitored Sonarr/Radarr language repairs. It must never grab a candidate by
  itself; apply a reviewed candidate through the existing explicit upgrade
  helpers so the required dry-run-first workflow remains intact.
- The private-tracker audit writes secret-free HTML and JSON summaries under
  `state/private-trackers.*`. Never include torrent announce URLs, passkeys,
  account identifiers, or credentials in those summaries.
- Telegram remains completion-only. Recipient delivery fingerprints may be
  stored in NAS-local state so a failed recipient can be retried without
  repeating successful deliveries; do not add routine start/search/import
  messages.
- Telegram posters normally resolve through Arr download history. Directly
  dispatched private packs have no Arr download record, so their managed
  `sonarr-series-N` or `radarr-movie-N` qBittorrent tag is the safe poster
  fallback. Poster troubleshooting must not resend an already delivered
  completion notification.
- For `btarg-series-pack` torrents, qBittorrent completion is not enough to
  notify. Wait for `btarg-import-verified`, then send the single completion
  message with wording that the series is available in Sonarr. Existing
  recipients that were already notified must not receive a duplicate.

- Telegram synchronizes one account across its devices, so a new device on an
  existing account requires no recipient change. For another person's
  account, have them start the bot and send `/registrar CODIGO`, then run
  `make register-telegram-recipient CODE=CODIGO`. This updates the NAS-local
  `chatIds` list and sends a test without displaying or manually copying any
  account identifier. Registration codes must use only letters, numbers,
  underscores, or hyphens and be 6-64 characters long.

- For monitored-library language upgrades, always run the Sonarr and Radarr
  upgrade helpers with `--dry-run` first, inspect every proposed release, then
  run without `--dry-run` only for safe language improvements.
- Automatic monitored-library upgrades are limited to the known private
  indexers. Public interactive results remain manual fallback and must never be
  grabbed by the batch upgrade helpers.
- Outstanding Seerr movie requests are retried automatically against known
  private indexers. Require Spanish for the first 14 days, then permit an
  English/original private fallback; always rank language before tracker.
- Reconsider completed Seerr movie requests when their library file is later
  removed as incorrect. Tag each dispatched release with a stable fingerprint;
  a `language-mismatch` blocks only that fingerprint, not the whole request.
- Stale incomplete public torrents are blocklisted automatically after the
  guarded metadata, availability, or no-connection timeout. Unknown and private
  torrents fail closed and are never removed by that workflow.
- Reject executable-like release titles and inspect private torrent members
  while stopped before allowing the payload to download.
- Slow release searches retry once. If a title still times out, it is skipped
  and the rest of the audit continues; revisit skipped items separately.
- Treat connection resets and remote disconnects from Arr release searches as
  retryable GET failures. A persistent failure must skip only that episode or
  series rather than aborting the full language-repair report.
- The hardlink audit indexes Downloads once and checks up to 500 recent media
  files. Do not reduce it to a tiny recent window that can contain only copied
  or transcoded imports and produce a false failure.
- ExtraTorrent.st is intentionally disabled because its empty-result test is
  unreliable. Public sources remain interactive-only fallbacks.
- Full deploys finish with the live health validator. Keep the NAS OpenSSH
  post-quantum warning visible; it requires a vendor-supported SSH upgrade and
  must not be hidden as though the server had been secured.
- Recyclarr may overwrite managed custom-format scores. Full deploys must run
  `configure-servarr.py` again after both Recyclarr syncs before applying the
  Radarr-specific post-policy.
- Normal full deploys use Dispatcharr `--check-only`; the complete playlist and
  EPG refresh is explicit through `make configure-iptv` or
  `DISPATCHARR_SYNC_ON_DEPLOY=1` because the external EPG can exceed ten
  minutes.
- Docker operations in full deploys have explicit safety deadlines. If the NAS
  is saturated, report load and storage context and exit without removing
  containers instead of leaving an unbounded SSH deployment process.
- `audit-imported-audio.py` reviews recent Arr imports. It may tag a proven
  English-only torrent whose managed filename claims `[LATINO]` or
  `[CASTELLANO]` as `language-mismatch`, but must not delete its library file or
  torrent. Undefined audio stays review-only.
- Full deploys run `check-nas-preflight.py` before Docker changes. Focused
  reliability changes use `make deploy-reliability`; do not repeat a full
  deploy solely to install observability scripts or systemd deadlines.
- `state/media-health.json` and `.html` are the secret-free combined health
  summary. A BTArg worker with active progress unchanged for over two hours may
  be stopped as a control group; retain its torrent and temporary files.
- All scheduled one-shot services have explicit runtime limits. Long BTArg
  conversions retain a 36-hour overall ceiling plus their per-file conversion
  limits.
- Validate changes with `python3 -m unittest discover -s tests`,
  `git diff --check`, and relevant live read-only audits before committing.
- Keep deployment scripts scoped and idempotent. Avoid full-stack restarts for
  tracker or language-policy-only changes.
