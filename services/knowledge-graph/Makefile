.PHONY: run test test-integration lint migrate migrate-new .env-check

.env-check:
	@test -f configs/dev.local.env || \
		(echo "ERROR: configs/dev.local.env missing - run: cp configs/dev.local.env.example configs/dev.local.env" && exit 1)

run: .env-check
	uvicorn knowledge_graph.app:create_app --factory --reload --port 8007

test:
	pytest tests/ -m unit -v

test-integration:
	pytest tests/ -m integration -v

lint:
	ruff check src/ tests/
	mypy src/

migrate: .env-check
	set -a && . ./configs/dev.local.env && set +a && alembic upgrade head

migrate-new: .env-check
	set -a && . ./configs/dev.local.env && set +a && alembic revision --autogenerate -m "$(MSG)"
