# SPILLTRACE — developer entrypoint.
# Auto-detects the container runtime so the same Compose file works with
# Docker or Podman (this dev host has Podman only).

SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE := $(shell \
  if docker compose version >/dev/null 2>&1; then echo "docker compose"; \
  elif command -v docker-compose >/dev/null 2>&1; then echo "docker-compose"; \
  elif command -v podman-compose >/dev/null 2>&1; then echo "podman-compose"; \
  elif [ -x "$$HOME/.local/bin/podman-compose" ]; then echo "$$HOME/.local/bin/podman-compose"; \
  elif podman compose version >/dev/null 2>&1; then echo "podman compose"; \
  else echo "NO_COMPOSE"; fi)

# The bind-mounted source tree is owned by the host user, so tool caches must live
# outside it, and mypy needs /app/backend as cwd to discover pyproject.toml.
TOOL_ENV := -e RUFF_CACHE_DIR=/tmp/ruff_cache -e MYPY_CACHE_DIR=/tmp/mypy_cache \
            -e PYTEST_ADDOPTS=-p\ no:cacheprovider
BACKEND_EXEC := $(COMPOSE) exec -T $(TOOL_ENV) -w /app/backend api
DC := $(COMPOSE)

.PHONY: help
help: ## Show this help
	@echo "SPILLTRACE — make targets   (runtime: $(COMPOSE))"
	@grep -hE '^[a-zA-Z0-9_.-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

.PHONY: check-runtime
check-runtime: ## Verify a container runtime is available
	@if [ "$(COMPOSE)" = "NO_COMPOSE" ]; then \
	  echo "ERROR: no compose runtime found. Install Docker Desktop, or 'pip install --user podman-compose'."; exit 1; fi
	@echo "runtime: $(COMPOSE)"

.PHONY: check-env
check-env: ## Verify .env exists and required variables are set
	@test -f .env || { echo "ERROR: .env missing. Run 'make init-env'."; exit 1; }
	@bash infra/scripts/check_env.sh

.PHONY: init-env
init-env: ## Create .env from .env.example with generated secrets
	@bash infra/scripts/init_env.sh

.PHONY: up
up: check-runtime check-env ## Start the whole stack
	$(DC) up -d --build
	@$(MAKE) --no-print-directory wait-healthy

.PHONY: down
down: ## Stop the stack (keeps volumes)
	$(DC) down

.PHONY: clean
clean: ## Stop the stack and DELETE all volumes (destructive)
	$(DC) down -v

.PHONY: ps
ps: ## Show service status
	$(DC) ps

.PHONY: logs
logs: ## Tail logs (SERVICE=api make logs)
	$(DC) logs -f $(SERVICE)

.PHONY: wait-healthy
wait-healthy: ## Block until API answers /health
	@bash infra/scripts/wait_healthy.sh

.PHONY: build
build: check-runtime ## Build all images
	$(DC) build

.PHONY: build-ml
build-ml: check-runtime ## Rebuild the backend image with PyTorch included
	$(DC) build --build-arg INSTALL_ML=true api worker

.PHONY: migrate
migrate: ## Apply database migrations
	$(BACKEND_EXEC) alembic upgrade head

.PHONY: migrate-down
migrate-down: ## Roll back one migration
	$(BACKEND_EXEC) alembic downgrade -1

.PHONY: makemigration
makemigration: ## Autogenerate a migration (M="message")
	$(COMPOSE) exec -T --user root $(TOOL_ENV) -w /app/backend api alembic revision --autogenerate -m "$(M)"
	python3 infra/scripts/postprocess_migration.py $$(ls -t backend/src/spilltrace/db/migrations/versions/*.py | head -1)

.PHONY: seed
seed: ## Seed users, model version and the demo case
	$(BACKEND_EXEC) python -m spilltrace.db.seed

.PHONY: db-reset
db-reset: ## Drop, re-migrate and re-seed the database (destructive)
	$(BACKEND_EXEC) python -m spilltrace.db.reset
	@$(MAKE) --no-print-directory migrate seed

.PHONY: psql
psql: ## Open a psql shell
	$(DC) exec postgres psql -U $${POSTGRES_USER:-spilltrace} -d $${POSTGRES_DB:-spilltrace}

.PHONY: shell
shell: ## Python shell inside the API container
	$(DC) exec api python

.PHONY: test
test: ## Run the full backend test suite
	$(BACKEND_EXEC) python -m pytest -q

.PHONY: test-unit
test-unit: ## Unit tests only (no services required)
	$(BACKEND_EXEC) python -m pytest -q tests/unit

.PHONY: test-integration
test-integration: ## Integration tests (needs postgres/redis/minio)
	$(BACKEND_EXEC) python -m pytest -q tests/integration

.PHONY: test-gis
test-gis: ## GIS/PostGIS tests
	$(BACKEND_EXEC) python -m pytest -q tests/gis

.PHONY: test-e2e
test-e2e: ## End-to-end investigation tests
	$(BACKEND_EXEC) python -m pytest -q tests/e2e

.PHONY: test-frontend
test-frontend: ## Frontend unit/component tests
	$(DC) exec -T frontend npm run test -- --run

.PHONY: lint
lint: ## Lint backend and frontend
	$(BACKEND_EXEC) ruff check src tests
	$(BACKEND_EXEC) ruff format --check src tests
	$(DC) exec -T frontend npm run lint

.PHONY: format
format: ## Auto-format backend and frontend
	$(COMPOSE) exec -T --user root $(TOOL_ENV) -w /app/backend api ruff format src tests
	$(COMPOSE) exec -T --user root $(TOOL_ENV) -w /app/backend api ruff check --fix src tests
	$(DC) exec -T frontend npm run format

.PHONY: typecheck
typecheck: ## mypy + tsc
	$(BACKEND_EXEC) mypy src
	$(DC) exec -T frontend npm run typecheck

.PHONY: audit-secrets
audit-secrets: ## Fail if any credential-shaped value can reach the browser bundle
	bash infra/scripts/audit_secrets.sh

.PHONY: demo
demo: ## Create the deterministic SYNTHETIC demo case
	$(BACKEND_EXEC) python -m spilltrace.demo.create --scenario kutch-01 --seed 42

.PHONY: quality-gate
quality-gate: lint typecheck test audit-secrets ## Everything that must pass before COMPLETED
	@echo "quality gate: PASS"
