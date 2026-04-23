.PHONY: help lint typecheck test-unit test-e2e test-all test-arch infra-up infra-down qa qa-exhaustive qa-exhaustive-backend qa-exhaustive-frontend qa-live-stack qa-contract dev dev-down dev-reset dev-logs dev-ps dev-rebuild dev-clean seed

# ── Default target ────────────────────────────────────────────────────────────

help:
	@echo "Worldview Platform — Test Targets"
	@echo ""
	@echo "  make lint            Ruff check + format check (no infra)"
	@echo "  make typecheck       mypy for all services and libs"
	@echo "  make test-unit       All unit + contract tests (no infra)"
	@echo "  make test-arch       Architecture/standards compliance tests"
	@echo "  make test-all        Full platform: lint + unit + integration + e2e"
	@echo "  make infra-up        Start test Docker Compose stack (--profile all)"
	@echo "  make infra-down      Stop test Docker Compose stack"
	@echo "  make qa              lint + typecheck + test-unit (CI gate)"
	@echo "  make qa-exhaustive   Exhaustive QA vs live dev stack (make dev + make seed first)"
	@echo "  make qa-live-stack   Frontend vs real API, no mocks (exposes broken backends)"
	@echo "  make qa-contract     Verify mock fixtures match real API shapes"
	@echo ""
	@echo "  make test-unit SERVICE=<svc>   Unit tests for a single service"
	@echo "  make test-e2e  SERVICE=<svc>   E2E tests for a single service"
	@echo "  make infra-up  PROFILE=<p>     Start a specific Compose profile"
	@echo ""
	@echo "Dev environment setup:"
	@echo "  (worldview-gitops)/scripts/setup-dev.sh   Copy dev env files from private repo"
	@echo "  make dev                                   Start full Docker Compose dev stack"
	@echo "  make dev-clean                             Remove local docker.env files"
	@echo "  make seed                                  Load sample data"

# ── Lint ──────────────────────────────────────────────────────────────────────

lint:
	uvx ruff@0.4.0 check libs/ services/ tests/
	uvx ruff@0.4.0 format --check libs/ services/ tests/

# ── Type check ────────────────────────────────────────────────────────────────

typecheck:
	@for svc_src in services/*/src; do \
	  svc_dir=$$(dirname "$$svc_src"); \
	  if [ -f "$$svc_dir/mypy.ini" ]; then \
	    echo "mypy: $$svc_dir"; \
	    mypy "$$svc_src" --config-file "$$svc_dir/mypy.ini" || exit 1; \
	  fi; \
	done
	@for lib_src in libs/*/src; do \
	  lib_dir=$$(dirname "$$lib_src"); \
	  if [ -f "$$lib_dir/mypy.ini" ]; then \
	    echo "mypy: $$lib_dir"; \
	    mypy "$$lib_src" --config-file "$$lib_dir/mypy.ini" || exit 1; \
	  fi; \
	done

# ── Unit tests ────────────────────────────────────────────────────────────────

test-unit:
	@./scripts/test-libs.sh
ifdef SERVICE
	@./scripts/run-unit-tests.sh services/$(SERVICE)
else
	@./scripts/run-unit-tests.sh
endif

# ── E2E tests ─────────────────────────────────────────────────────────────────

test-e2e:
ifdef SERVICE
	./scripts/run-service-e2e.sh $(SERVICE)
else
	./scripts/test-full.sh --no-cleanup
endif

# ── Full suite (all layers) ───────────────────────────────────────────────────

test-all:
	./scripts/test-full.sh

# ── Infrastructure ────────────────────────────────────────────────────────────

infra-up:
	docker compose -f infra/compose/docker-compose.test.yml \
	  --profile $${PROFILE:-all} up --build --wait

infra-down:
	docker compose -f infra/compose/docker-compose.test.yml down -v

# ── CI gate ───────────────────────────────────────────────────────────────────

qa: lint typecheck test-unit

# ── Exhaustive QA (requires dev stack running: make dev + make seed) ──────

.PHONY: qa-exhaustive qa-exhaustive-backend qa-exhaustive-frontend

## Run the full exhaustive QA layer (backend + frontend) against the live dev stack
qa-exhaustive: qa-exhaustive-backend qa-exhaustive-frontend

## Backend exhaustive QA: endpoint coverage, auth, security, schema validation
qa-exhaustive-backend:
	@echo "=== Running backend exhaustive QA ==="
	python3 scripts/qa_exhaustive.py

## Frontend exhaustive QA: all routes, states, screenshots, a11y, security headers
qa-exhaustive-frontend:
	@echo "=== Running frontend exhaustive QA ==="
	cd apps/worldview-web && npx playwright test e2e/qa-exhaustive.spec.ts --reporter=list

## Frontend live-stack QA: real API calls, no mocks — exposes broken backends
qa-live-stack:
	@echo "=== Running frontend live-stack QA (no mocks) ==="
	cd apps/worldview-web && npx playwright test e2e/qa-live-stack.spec.ts --project=chromium --reporter=list

## Contract alignment: verify frontend mock fixtures match real API response shapes
qa-contract:
	@echo "=== Running contract alignment check ==="
	python3 scripts/qa_contract_alignment.py

# ── Architecture tests ─────────────────────────────────────────────────────

test-arch:
	python -m pytest tests/architecture/ -v --tb=short

# ── Development Environment ──────────────────────────────────────────────────

# ── Development Environment ──────────────────────────────────────────────────
# Dev env files (docker.env) are NOT generated here — they live in the private
# worldview-gitops repo. Run scripts/setup-dev.sh from worldview-gitops first.
# See: https://github.com/your-org/worldview-gitops/blob/main/scripts/setup-dev.sh

## Start the full development stack (all services + dev tools + MailHog)
dev:
	$(COMPOSE_DEV) up -d
	@echo ""
	@echo "🚀 Worldview dev stack is running!"
	@echo ""
	@echo "  Frontend:        http://localhost:3001"
	@echo "  API Gateway:     http://localhost:8000"
	@echo "  MailHog:         http://localhost:8025"
	@echo "  pgweb:           http://localhost:8091"
	@echo "  Kafka UI:        http://localhost:8092"
	@echo "  MinIO Console:   http://localhost:7481"
	@echo ""

COMPOSE_DEV := docker compose -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.dev.yml --profile infra

## Stop the development stack (--timeout 5 avoids 30s hang on workers without SIGTERM handlers)
dev-down:
	$(COMPOSE_DEV) down --timeout 5

## Stop and remove all data (clean reset)
dev-reset:
	$(COMPOSE_DEV) down -v --remove-orphans --timeout 5

## Show logs for all services (follow mode)
dev-logs:
	$(COMPOSE_DEV) logs -f --tail=50

## Show container health status
dev-ps:
	$(COMPOSE_DEV) ps

## Rebuild all images and restart
dev-rebuild:
	$(COMPOSE_DEV) up -d --build

## Remove local docker.env files (re-run setup-dev.sh from worldview-gitops to restore)
dev-clean:
	@find services/*/configs -name "docker.env" -delete
	@echo "docker.env files removed. Run scripts/setup-dev.sh from worldview-gitops to restore."

## Seed development data (instruments, entities, sample articles)
seed:
	@./scripts/seed-dev-data.sh

# ── Observability stack ─────────────────────────────────────────────────────

COMPOSE_MONITORING := docker compose -f infra/compose/docker-compose.yml --profile monitoring

## Start the monitoring stack (Prometheus, Grafana, Alertmanager, Alloy, Loki, Tempo).
## Run AFTER `make dev` — monitoring targets the running dev services.
## Grafana: http://localhost:3000  Prometheus: http://localhost:9090
## Alertmanager: http://localhost:9093
monitoring:
	$(COMPOSE_MONITORING) up -d
	@echo ""
	@echo "Observability stack is running:"
	@echo "  Grafana:        http://localhost:3000  (admin/admin)"
	@echo "  Prometheus:     http://localhost:9090"
	@echo "  Alertmanager:   http://localhost:9093"
	@echo ""
	@echo "Use 'make monitoring-down' to stop."

## Stop the monitoring stack
monitoring-down:
	$(COMPOSE_MONITORING) down

.PHONY: monitoring monitoring-down
