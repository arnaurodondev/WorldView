FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic/ alembic/
COPY alembic.ini .
COPY seeds/ seeds/
COPY scripts/ scripts/
COPY entrypoint.sh .

ENTRYPOINT ["/app/entrypoint.sh"]
