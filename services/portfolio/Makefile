VENV      := .venv
PYTHON    := $(VENV)/bin/python
UV        := uv
LIBS_ROOT := ../../libs

.PHONY: run run-dispatcher test test-integration test-contract test-e2e test-all lint migrate migrate-new .env-check setup

setup:
	@test -d $(VENV) || $(UV) venv --python 3.11 $(VENV)
	$(UV) pip install --python $(PYTHON) \
		-e $(LIBS_ROOT)/common \
		-e $(LIBS_ROOT)/contracts \
		-e $(LIBS_ROOT)/messaging \
		-e $(LIBS_ROOT)/observability \
		-e $(LIBS_ROOT)/storage \
		-e ".[dev]"

.env-check:
	@test -f configs/dev.local.env || \
		(echo "ERROR: configs/dev.local.env missing - run: cp configs/dev.local.env.example configs/dev.local.env" && exit 1)

run: .env-check
	set -a && . ./configs/dev.local.env && set +a && $(VENV)/bin/uvicorn portfolio.app:create_app --factory --reload --port 8001

run-dispatcher: .env-check
	set -a && . ./configs/dev.local.env && set +a && $(VENV)/bin/python -m portfolio.messaging.dispatcher_main

# Unit tests — no env sourcing required (all infra is mocked)
test:
	$(VENV)/bin/pytest tests/ -m unit -v

# Integration tests — require running Postgres (testcontainers or dev infra)
test-integration: .env-check
	set -a && . ./configs/dev.local.env && set +a && $(VENV)/bin/pytest tests/ -m integration -v

test-contract:
	$(VENV)/bin/pytest tests/ -m contract -v

# E2E tests — starts docker-compose.test.yml, runs tests against localhost:8001, tears down
test-e2e: .env-check
	@docker compose -f ../../infra/compose/docker-compose.test.yml --profile portfolio-test up --build --wait; \
	COMPOSE_EXIT=$$?; \
	if [ $$COMPOSE_EXIT -ne 0 ]; then \
		docker compose -f ../../infra/compose/docker-compose.test.yml --profile portfolio-test down -v; \
		exit $$COMPOSE_EXIT; \
	fi; \
	set -a && . ./configs/dev.local.env && set +a; \
	$(VENV)/bin/pytest tests/e2e/ -v; \
	EXIT=$$?; \
	docker compose -f ../../infra/compose/docker-compose.test.yml --profile portfolio-test down -v; \
	exit $$EXIT

test-all: .env-check
	set -a && . ./configs/dev.local.env && set +a && $(VENV)/bin/pytest tests/ -v

lint:
	$(VENV)/bin/ruff check src/ tests/
	$(VENV)/bin/mypy src/

migrate: .env-check
	set -a && . ./configs/dev.local.env && set +a && $(VENV)/bin/alembic upgrade head

migrate-new: .env-check
	set -a && . ./configs/dev.local.env && set +a && $(VENV)/bin/alembic revision --autogenerate -m "$(MSG)"
