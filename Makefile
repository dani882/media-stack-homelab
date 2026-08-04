.PHONY: validate lint shellcheck bootstrap check deploy configure-prowlarr

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
