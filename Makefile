.PHONY: dry-run-radarr-policy validate lint shellcheck test bootstrap check deploy backup dry-run-backup restore dry-run-restore configure-prowlarr dry-run-prowlarr configure-qbittorrent configure-radarr configure-radarr-policy audit-radarr-releases configure-servarr configure-seerr dry-run-seerr configure-profilarr dry-run-configure-profilarr configure-profilarr-pilot dry-run-configure-profilarr-pilot sync-profilarr dry-run-sync-profilarr sync-recyclarr check-media-live audit-bazarr audit-seerr audit-private-trackers audit-legacy-mounts audit-seerr-request-flow grab-prowlarr-release audit-hardlinks verify-hardlinks import-sonarr-title-matched dry-run-import-sonarr-title-matched install-media-observability dry-run-cleanup-public-imported cleanup-public-imported dry-run-cleanup-sonarr-dangerous cleanup-sonarr-dangerous dry-run-cleanup-radarr-dangerous cleanup-radarr-dangerous dry-run-cleanup-sonarr-normal cleanup-sonarr-normal dry-run-cleanup-radarr-normal cleanup-radarr-normal

validate:
	@./scripts/validate.sh

shellcheck:
	@shellcheck scripts/*.sh
	@find scripts/bootstrap -name "*.sh" -exec shellcheck {} \;

lint:
	@yamllint .

bootstrap:
	@./scripts/bootstrap.sh

test:
	@python3 -m unittest discover -s tests -p 'test_*.py'

check: shellcheck lint validate test

deploy:
	@./scripts/deploy.sh

backup:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cd /volume1/docker/media-stack && \
	   sudo -n ./backup.sh"

dry-run-backup:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cd /volume1/docker/media-stack && \
	   sudo -n ./backup.sh --dry-run"

restore:
	@test -n "$${BACKUP}" || \
	  { echo "ERROR: BACKUP is required"; exit 1; }
	@case "$${BACKUP}" in \
	  /volume1/docker/media-stack/backups/media-stack-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z.tar.zst) ;; \
	  *) echo "ERROR: Invalid media-stack backup path"; exit 1 ;; \
	esac
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cd /volume1/docker/media-stack && \
	   sudo -n ./restore.sh '$${BACKUP}'"

dry-run-restore:
	@test -n "$${BACKUP}" || \
	  { echo "ERROR: BACKUP is required"; exit 1; }
	@case "$${BACKUP}" in \
	  /volume1/docker/media-stack/backups/media-stack-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z.tar.zst) ;; \
	  *) echo "ERROR: Invalid media-stack backup path"; exit 1 ;; \
	esac
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cd /volume1/docker/media-stack && \
	   sudo -n ./restore.sh --dry-run '$${BACKUP}'"

configure-prowlarr:
	@ssh -t "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cd /volume1/docker/media-stack && \
	   sudo python3 ./configure-prowlarr.py"

sync-recyclarr:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cd /volume1/docker/media-stack && \
	   sudo -n docker compose run --rm recyclarr \
	     sync sonarr --instance series && \
	   sudo -n docker compose run --rm recyclarr \
	     sync radarr --instance movies && \
	   sudo -n python3 ./configure-radarr-policy.py"

sync-profilarr:
	@$(MAKE) configure-profilarr
	@$(MAKE) configure-profilarr-pilot

dry-run-sync-profilarr:
	@$(MAKE) dry-run-configure-profilarr
	@$(MAKE) dry-run-configure-profilarr-pilot

configure-servarr:
	@ssh -t "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cd /volume1/docker/media-stack && \
	   sudo python3 ./configure-servarr.py"

configure-seerr:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cd /volume1/docker/media-stack && \
	   sudo -n python3 ./configure-seerr.py"

dry-run-seerr:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cd /volume1/docker/media-stack && \
	   sudo -n python3 ./configure-seerr.py --dry-run"

configure-profilarr:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cd /volume1/docker/media-stack && \
	   sudo -n python3 ./configure-profilarr.py"

dry-run-configure-profilarr:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cd /volume1/docker/media-stack && \
	   sudo -n python3 ./configure-profilarr.py --dry-run"

configure-profilarr-pilot:
	@tmp_script="/tmp/configure-profilarr-sync-$$$$.py"; \
	tmp_config="/tmp/profilarr-pilot-sync-$$$$.json"; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cat > '$$tmp_script'" \
	  < scripts/configure-profilarr-sync.py; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cat > '$$tmp_config'" \
	  < stacks/media/profilarr/pilot-sync.json; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n install -m 755 '$$tmp_script' /volume1/docker/media-stack/configure-profilarr-sync.py && \
	   sudo -n install -d -m 755 /volume1/docker/media-stack/profilarr && \
	   sudo -n install -m 644 '$$tmp_config' /volume1/docker/media-stack/profilarr/pilot-sync.json && \
	   rm -f '$$tmp_script' '$$tmp_config' && \
	   cd /volume1/docker/media-stack && \
	   sudo -n python3 ./configure-profilarr-sync.py \
	     --config /volume1/docker/media-stack/profilarr/pilot-sync.json \
	     --run-sync \
	     --wait"

dry-run-configure-profilarr-pilot:
	@tmp_script="/tmp/configure-profilarr-sync-$$$$.py"; \
	tmp_config="/tmp/profilarr-pilot-sync-$$$$.json"; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cat > '$$tmp_script'" \
	  < scripts/configure-profilarr-sync.py; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cat > '$$tmp_config'" \
	  < stacks/media/profilarr/pilot-sync.json; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n install -m 755 '$$tmp_script' /volume1/docker/media-stack/configure-profilarr-sync.py && \
	   sudo -n install -d -m 755 /volume1/docker/media-stack/profilarr && \
	   sudo -n install -m 644 '$$tmp_config' /volume1/docker/media-stack/profilarr/pilot-sync.json && \
	   rm -f '$$tmp_script' '$$tmp_config' && \
	   cd /volume1/docker/media-stack && \
	   sudo -n python3 ./configure-profilarr-sync.py \
	     --config /volume1/docker/media-stack/profilarr/pilot-sync.json \
	     --run-sync \
	     --dry-run"

check-media-live:
	@tmp_script="/tmp/check-media-live-$$$$.py"; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cat > '$$tmp_script'" \
	  < scripts/check-media-live.py; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 '$$tmp_script'; rm -f '$$tmp_script'"

audit-bazarr:
	@tmp_script="/tmp/audit-bazarr-$$$$.py"; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cat > '$$tmp_script'" \
	  < scripts/audit-bazarr.py; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 '$$tmp_script'; rm -f '$$tmp_script'"

audit-seerr:
	@tmp_script="/tmp/audit-seerr-$$$$.py"; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cat > '$$tmp_script'" \
	  < scripts/audit-seerr.py; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 '$$tmp_script'; rm -f '$$tmp_script'"

audit-private-trackers:
	@tmp_script="/tmp/audit-private-trackers-$$$$.py"; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cat > '$$tmp_script'" \
	  < scripts/audit-private-trackers.py; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 '$$tmp_script'; rm -f '$$tmp_script'"

audit-legacy-mounts:
	@tmp_script="/tmp/audit-legacy-mounts-$$$$.py"; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cat > '$$tmp_script'" \
	  < scripts/audit-legacy-mounts.py; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 '$$tmp_script'; status=\$$?; rm -f '$$tmp_script'; exit \$$status"

audit-seerr-request-flow:
	@test -n "$${REQUEST_ID}" || { echo "ERROR: REQUEST_ID is required"; exit 1; }
	@tmp_script="/tmp/audit-seerr-request-flow-$$$$.py"; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cat > '$$tmp_script'" \
	  < scripts/audit-seerr-request-flow.py; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 '$$tmp_script' --request-id '$${REQUEST_ID}'; status=\$$?; rm -f '$$tmp_script'; exit \$$status"

grab-prowlarr-release:
	@test -n "$${QUERY}" || { echo "ERROR: QUERY is required"; exit 1; }
	@test -n "$${TITLE}" || { echo "ERROR: TITLE is required"; exit 1; }
	@test -n "$${INDEXER_ID}" || { echo "ERROR: INDEXER_ID is required"; exit 1; }
	@test "$${MEDIA_TYPE:-tv}" = movie -o -n "$${TVDB_ID}" || { echo "ERROR: TVDB_ID is required for TV releases"; exit 1; }
	@test "$${MEDIA_TYPE:-tv}" != movie -o -n "$${TMDB_ID}" || { echo "ERROR: TMDB_ID is required for movie releases"; exit 1; }
	@test -n "$${SEED_TIME_MINUTES}" || { echo "ERROR: SEED_TIME_MINUTES is required"; exit 1; }
	@test -n "$${TAGS}" || { echo "ERROR: TAGS is required"; exit 1; }
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 -u - --query '$${QUERY}' --title '$${TITLE}' --indexer-id '$${INDEXER_ID}' --media-type '$${MEDIA_TYPE:-tv}' $(if $(TVDB_ID),--tvdb-id '$(TVDB_ID)') $(if $(TMDB_ID),--tmdb-id '$(TMDB_ID)') --category '$${CATEGORY:-tv}' --seed-time-minutes '$${SEED_TIME_MINUTES}' --tags '$${TAGS}' $(if $(DRY_RUN),--dry-run)" \
	  < scripts/grab-prowlarr-release.py

audit-hardlinks:
	@tmp_script="/tmp/audit-hardlinks-$$$$.py"; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cat > '$$tmp_script'" \
	  < scripts/audit-hardlinks.py; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 '$$tmp_script'; rm -f '$$tmp_script'"

dry-run-cleanup-public-imported:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 /volume1/docker/media-stack/cleanup-public-imported.py --dry-run"

cleanup-public-imported:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 /volume1/docker/media-stack/cleanup-public-imported.py"

verify-hardlinks:
	@test -n "$${DOWNLOAD}" || \
	  { echo "ERROR: DOWNLOAD is required"; exit 1; }
	@test -n "$${LIBRARY}" || \
	  { echo "ERROR: LIBRARY is required"; exit 1; }
	@tmp_script="/tmp/verify-hardlinks-$$$$.py"; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cat > '$$tmp_script'" \
	  < scripts/verify-hardlinks.py; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 '$$tmp_script' \
	     --download '$${DOWNLOAD}' \
	     --library '$${LIBRARY}'; \
	   rm -f '$$tmp_script'"

dry-run-import-sonarr-title-matched:
	@test -n "$${SERIES_ID}" || { echo "ERROR: SERIES_ID is required"; exit 1; }
	@test -n "$${SOURCE}" || { echo "ERROR: SOURCE is required"; exit 1; }
	@tmp_script="/tmp/import-sonarr-title-matched-$$$$.py"; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" "cat > '$$tmp_script'" < scripts/media/import-sonarr-title-matched.py; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" "sudo -n python3 '$$tmp_script' --series-id '$${SERIES_ID}' --source '$${SOURCE}'; rm -f '$$tmp_script'"

import-sonarr-title-matched:
	@test -n "$${SERIES_ID}" || { echo "ERROR: SERIES_ID is required"; exit 1; }
	@test -n "$${SOURCE}" || { echo "ERROR: SOURCE is required"; exit 1; }
	@tmp_script="/tmp/import-sonarr-title-matched-$$$$.py"; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" "cat > '$$tmp_script'" < scripts/media/import-sonarr-title-matched.py; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" "sudo -n python3 '$$tmp_script' --series-id '$${SERIES_ID}' --source '$${SOURCE}' --apply; rm -f '$$tmp_script'"

install-media-observability:
	@tmp_monitor="/tmp/monitor-media-stack-$$$$.sh"; \
	tmp_live="/tmp/check-media-live-$$$$.py"; \
	tmp_bazarr="/tmp/audit-bazarr-$$$$.py"; \
	tmp_seerr="/tmp/audit-seerr-$$$$.py"; \
	tmp_private="/tmp/audit-private-trackers-$$$$.py"; \
	tmp_public_cleanup="/tmp/cleanup-public-imported-$$$$.py"; \
	tmp_hardlink_py="/tmp/audit-hardlinks-$$$$.py"; \
	tmp_health="/tmp/media-stack-healthcheck-$$$$.service"; \
	tmp_health_timer="/tmp/media-stack-healthcheck-$$$$.timer"; \
	tmp_hardlinks="/tmp/media-stack-hardlink-audit-$$$$.service"; \
	tmp_hardlinks_timer="/tmp/media-stack-hardlink-audit-$$$$.timer"; \
	tmp_public_cleanup_service="/tmp/media-stack-public-cleanup-$$$$.service"; \
	tmp_public_cleanup_timer="/tmp/media-stack-public-cleanup-$$$$.timer"; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" "cat > '$$tmp_monitor'" < scripts/monitor-media-stack.sh; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" "cat > '$$tmp_live'" < scripts/check-media-live.py; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" "cat > '$$tmp_bazarr'" < scripts/audit-bazarr.py; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" "cat > '$$tmp_seerr'" < scripts/audit-seerr.py; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" "cat > '$$tmp_private'" < scripts/audit-private-trackers.py; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" "cat > '$$tmp_public_cleanup'" < scripts/cleanup-public-imported.py; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" "cat > '$$tmp_hardlink_py'" < scripts/audit-hardlinks.py; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" "cat > '$$tmp_health'" < stacks/media/systemd/media-stack-healthcheck.service; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" "cat > '$$tmp_health_timer'" < stacks/media/systemd/media-stack-healthcheck.timer; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" "cat > '$$tmp_hardlinks'" < stacks/media/systemd/media-stack-hardlink-audit.service; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" "cat > '$$tmp_hardlinks_timer'" < stacks/media/systemd/media-stack-hardlink-audit.timer; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" "cat > '$$tmp_public_cleanup_service'" < stacks/media/systemd/media-stack-public-cleanup.service; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" "cat > '$$tmp_public_cleanup_timer'" < stacks/media/systemd/media-stack-public-cleanup.timer; \
	ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" "sudo -n install -m 755 '$$tmp_monitor' /volume1/docker/media-stack/monitor-media-stack.sh && \
	  sudo -n install -m 755 '$$tmp_live' /volume1/docker/media-stack/check-media-live.py && \
	  sudo -n install -m 755 '$$tmp_bazarr' /volume1/docker/media-stack/audit-bazarr.py && \
	  sudo -n install -m 755 '$$tmp_seerr' /volume1/docker/media-stack/audit-seerr.py && \
	  sudo -n install -m 755 '$$tmp_private' /volume1/docker/media-stack/audit-private-trackers.py && \
	  sudo -n install -m 755 '$$tmp_public_cleanup' /volume1/docker/media-stack/cleanup-public-imported.py && \
	  sudo -n install -m 755 '$$tmp_hardlink_py' /volume1/docker/media-stack/audit-hardlinks.py && \
	  sudo -n install -m 644 '$$tmp_health' /etc/systemd/system/media-stack-healthcheck.service && \
	  sudo -n install -m 644 '$$tmp_health_timer' /etc/systemd/system/media-stack-healthcheck.timer && \
	  sudo -n install -m 644 '$$tmp_hardlinks' /etc/systemd/system/media-stack-hardlink-audit.service && \
	  sudo -n install -m 644 '$$tmp_hardlinks_timer' /etc/systemd/system/media-stack-hardlink-audit.timer && \
	  sudo -n install -m 644 '$$tmp_public_cleanup_service' /etc/systemd/system/media-stack-public-cleanup.service && \
	  sudo -n install -m 644 '$$tmp_public_cleanup_timer' /etc/systemd/system/media-stack-public-cleanup.timer && \
	  sudo -n systemctl daemon-reload && \
	  sudo -n systemctl enable --now media-stack-healthcheck.timer media-stack-hardlink-audit.timer media-stack-public-cleanup.timer && \
	  rm -f '$$tmp_monitor' '$$tmp_live' '$$tmp_bazarr' '$$tmp_seerr' '$$tmp_private' '$$tmp_public_cleanup' '$$tmp_hardlink_py' '$$tmp_health' '$$tmp_health_timer' '$$tmp_hardlinks' '$$tmp_hardlinks_timer' '$$tmp_public_cleanup_service' '$$tmp_public_cleanup_timer'"

configure-qbittorrent:
	@ssh -t "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cd /volume1/docker/media-stack && \
	   sudo python3 ./configure-qbittorrent.py"

configure-radarr:
	@test -n "$${MOVIE_ID}" || \
	  { echo "ERROR: MOVIE_ID is required"; exit 1; }
	@test -n "$${DESTINATION}" || \
	  { echo "ERROR: DESTINATION must be movies or kids"; exit 1; }
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cd /volume1/docker/media-stack && \
	   sudo -n python3 ./configure-radarr.py \
	     --movie-id '$${MOVIE_ID}' \
	     --destination '$${DESTINATION}'"

dry-run-prowlarr:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cd /volume1/docker/media-stack && \
	   sudo -n python3 ./configure-prowlarr.py --dry-run"

audit-radarr-releases:
	@test -n "$${MOVIE_ID}" || \
	  { echo "ERROR: MOVIE_ID is required"; exit 1; }
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cd /volume1/docker/media-stack && \
	   sudo -n python3 ./audit-radarr-releases.py \
	     --movie-id '$${MOVIE_ID}'"

configure-radarr-policy:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cd /volume1/docker/media-stack && \
	   sudo -n python3 ./configure-radarr-policy.py"

dry-run-radarr-policy:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "cd /volume1/docker/media-stack && \
	   sudo -n python3 ./configure-radarr-policy.py --dry-run"

.PHONY: audit-latino

audit-latino:
	@if [ -z "$(SERIES)" ]; then \
		echo 'Usage: make audit-latino SERIES="Silo" [SEASON=2]'; \
		exit 1; \
	fi
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  'python3 /volume1/docker/media-stack/scripts/audit-sonarr-latino.py \
	    --series "$(SERIES)"$(if $(SEASON), --season $(SEASON),)'

.PHONY: cleanup-sonarr-downloads dry-run-cleanup-sonarr-downloads

cleanup-sonarr-downloads:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 \
	   /volume1/docker/media-stack/scripts/cleanup-sonarr-downloads.py"

dry-run-cleanup-sonarr-downloads:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 \
	   /volume1/docker/media-stack/scripts/cleanup-sonarr-downloads.py \
	   --dry-run"

dry-run-cleanup-sonarr-dangerous:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 \
	   /volume1/docker/media-stack/scripts/cleanup-sonarr-downloads.py \
	   --dry-run --dangerous-only"

cleanup-sonarr-dangerous:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 \
	   /volume1/docker/media-stack/scripts/cleanup-sonarr-downloads.py \
	   --dangerous-only"

dry-run-cleanup-sonarr-normal:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 \
	   /volume1/docker/media-stack/scripts/cleanup-sonarr-downloads.py \
	   --dry-run --normal-only"

cleanup-sonarr-normal:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 \
	   /volume1/docker/media-stack/scripts/cleanup-sonarr-downloads.py \
	   --normal-only"

.PHONY: upgrade-latino dry-run-upgrade-latino

upgrade-latino:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 \
	   /volume1/docker/media-stack/scripts/upgrade-sonarr-latino.py \
	   $(if $(SERIES),--series '$(SERIES)',) \
	   $(if $(SEASON),--season '$(SEASON)',)"

dry-run-upgrade-latino:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 \
	   /volume1/docker/media-stack/scripts/upgrade-sonarr-latino.py \
	   --dry-run \
	   $(if $(SERIES),--series '$(SERIES)',) \
	   $(if $(SEASON),--season '$(SEASON)',)"

.PHONY: audit-radarr-latino upgrade-radarr-latino dry-run-upgrade-radarr-latino

audit-radarr-latino:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "python3 \
	   /volume1/docker/media-stack/scripts/audit-radarr-latino.py \
	   $(if $(MOVIE_ID),--movie-id '$(MOVIE_ID)',) \
	   $(if $(MOVIE),--movie '$(MOVIE)',)"

upgrade-radarr-latino:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "python3 \
	   /volume1/docker/media-stack/scripts/upgrade-radarr-latino.py \
	   $(if $(MOVIE_ID),--movie-id '$(MOVIE_ID)',) \
	   $(if $(MOVIE),--movie '$(MOVIE)',)"

dry-run-upgrade-radarr-latino:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "python3 \
	   /volume1/docker/media-stack/scripts/upgrade-radarr-latino.py \
	   --dry-run \
	   $(if $(MOVIE_ID),--movie-id '$(MOVIE_ID)',) \
	   $(if $(MOVIE),--movie '$(MOVIE)',)"

.PHONY: cleanup-radarr-downloads dry-run-cleanup-radarr-downloads

cleanup-radarr-downloads:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 \
	   /volume1/docker/media-stack/scripts/cleanup-radarr-downloads.py"

dry-run-cleanup-radarr-downloads:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 \
	   /volume1/docker/media-stack/scripts/cleanup-radarr-downloads.py \
	   --dry-run"

dry-run-cleanup-radarr-dangerous:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 \
	   /volume1/docker/media-stack/scripts/cleanup-radarr-downloads.py \
	   --dry-run --dangerous-only"

cleanup-radarr-dangerous:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 \
	   /volume1/docker/media-stack/scripts/cleanup-radarr-downloads.py \
	   --dangerous-only"

dry-run-cleanup-radarr-normal:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 \
	   /volume1/docker/media-stack/scripts/cleanup-radarr-downloads.py \
	   --dry-run --normal-only"

cleanup-radarr-normal:
	@ssh "$${NAS_USER:-jrivera}@$${NAS_HOST:-ugreen-nas}" \
	  "sudo -n python3 \
	   /volume1/docker/media-stack/scripts/cleanup-radarr-downloads.py \
	   --normal-only"
