.PHONY: validate lint shellcheck bootstrap check deploy

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
