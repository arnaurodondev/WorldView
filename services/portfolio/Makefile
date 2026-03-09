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
	$(VENV)/bin/uvicorn portfolio.app:create_app --factory --reload --port 8001

run-dispatcher: .env-check
	$(VENV)/bin/python -m portfolio.messaging.dispatcher_main

test:
	$(VENV)/bin/pytest tests/ -m unit -v

test-integration:
	$(VENV)/bin/pytest tests/ -m integration -v

test-contract:
	$(VENV)/bin/pytest tests/ -m contract -v

test-e2e:
	$(VENV)/bin/pytest tests/e2e/ -v

test-all:
	$(VENV)/bin/pytest tests/ -v

lint:
	$(VENV)/bin/ruff check src/ tests/
	$(VENV)/bin/mypy src/

migrate: .env-check
	set -a && . ./configs/dev.local.env && set +a && $(VENV)/bin/alembic upgrade head

migrate-new: .env-check
	set -a && . ./configs/dev.local.env && set +a && $(VENV)/bin/alembic revision --autogenerate -m "$(MSG)"
