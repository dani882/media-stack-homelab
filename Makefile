.PHONY: dry-run-radarr-policy validate lint shellcheck test bootstrap check deploy backup dry-run-backup configure-prowlarr dry-run-prowlarr configure-qbittorrent configure-radarr configure-radarr-policy audit-radarr-releases configure-servarr configure-seerr dry-run-seerr sync-recyclarr

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

configure-prowlarr:
	@ssh -t "$${NAS_USER:-jrivera}@$${NAS_HOST:-10.0.0.123}" \
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

configure-servarr:
	@ssh -t "$${NAS_USER:-jrivera}@$${NAS_HOST:-10.0.0.123}" \
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
