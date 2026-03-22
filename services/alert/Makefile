.PHONY: run test lint migrate

run:
	uvicorn alert.main:app --host 0.0.0.0 --port 8010 --reload

test:
	python -m pytest tests/ -x -q

lint:
	ruff check src/ tests/
	mypy src/

migrate:
	alembic upgrade head
