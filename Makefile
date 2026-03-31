.PHONY: help lint typecheck test-unit test-e2e test-all infra-up infra-down qa

# ── Default target ────────────────────────────────────────────────────────────

help:
	@echo "Worldview Platform — Test Targets"
	@echo ""
	@echo "  make lint            Ruff check + format check (no infra)"
	@echo "  make typecheck       mypy for all services and libs"
	@echo "  make test-unit       All unit + contract tests (no infra)"
	@echo "  make test-all        Full platform: lint + unit + integration + e2e"
	@echo "  make infra-up        Start test Docker Compose stack (--profile all)"
	@echo "  make infra-down      Stop test Docker Compose stack"
	@echo "  make qa              lint + typecheck + test-unit (CI gate)"
	@echo ""
	@echo "  make test-unit SERVICE=<svc>   Unit tests for a single service"
	@echo "  make test-e2e  SERVICE=<svc>   E2E tests for a single service"
	@echo "  make infra-up  PROFILE=<p>     Start a specific Compose profile"

# ── Lint ──────────────────────────────────────────────────────────────────────

lint:
	uvx ruff check libs/ services/ tests/
	uvx ruff format --check libs/ services/ tests/

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
