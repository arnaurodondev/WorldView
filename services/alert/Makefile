VENV      := .venv
PYTHON    := $(VENV)/bin/python
UV        := uv
LIBS_ROOT := ../../libs

.PHONY: run test test-integration test-all lint migrate migrate-new .env-check setup

setup:
	@test -d $(VENV) || $(UV) venv --python 3.11 $(VENV)
	$(UV) pip install --python $(PYTHON) \
		-e $(LIBS_ROOT)/common \
		-e $(LIBS_ROOT)/messaging \
		-e $(LIBS_ROOT)/observability \
		-e ".[dev]"

.env-check:
	@test -f configs/dev.local.env || \
		(echo "ERROR: configs/dev.local.env missing - run: cp configs/dev.local.env.example configs/dev.local.env" && exit 1)

run: .env-check
	$(VENV)/bin/uvicorn alert.app:create_app --factory --reload --port 8010

test:
	$(VENV)/bin/pytest tests/ -m unit -v

test-integration:
	@$(VENV)/bin/pytest tests/ -m integration -v; \
	EXIT=$$?; \
	if [ $$EXIT -eq 5 ]; then \
		echo "No integration tests collected (pytest exit 5)"; \
		exit 0; \
	fi; \
	exit $$EXIT

test-all:
	$(VENV)/bin/pytest tests/ -v

lint:
	$(VENV)/bin/ruff check src/ tests/
	$(VENV)/bin/mypy src/

migrate: .env-check
	set -a && . ./configs/dev.local.env && set +a && $(VENV)/bin/alembic upgrade head

migrate-new: .env-check
	set -a && . ./configs/dev.local.env && set +a && $(VENV)/bin/alembic revision --autogenerate -m "$(MSG)"
