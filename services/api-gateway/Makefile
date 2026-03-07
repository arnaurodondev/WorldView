.PHONY: run test test-integration lint migrate migrate-new

run:
	uvicorn api_gateway.app:create_app --factory --reload --port 8000

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
