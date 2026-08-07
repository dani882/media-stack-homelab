.PHONY: dry-run-radarr-policy validate lint shellcheck bootstrap check deploy configure-prowlarr dry-run-prowlarr configure-qbittorrent configure-radarr configure-radarr-policy audit-radarr-releases configure-servarr sync-recyclarr

validate:
	@./scripts/validate.sh

shellcheck:
	@shellcheck scripts/*.sh
	@find scripts/bootstrap -name "*.sh" -exec shellcheck {} \;

lint:
	@yamllint .

bootstrap:
	@./scripts/bootstrap.sh

check: shellcheck lint validate

deploy:
	@./scripts/deploy.sh

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
