.PHONY: run test test-integration lint migrate migrate-new

run:
	uvicorn portfolio.app:create_app --factory --reload --port 8001

test:
	pytest tests/ -m unit -v

test-integration:
	pytest tests/ -m integration -v

lint:
	ruff check src/ tests/
	mypy src/

migrate:
	alembic upgrade head

migrate-new:
	alembic revision --autogenerate -m "$(MSG)"
