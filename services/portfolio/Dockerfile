# syntax=docker/dockerfile:1
# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir uv==0.4.29

# Copy only pyproject.toml + src from each lib (no tests, caches, venvs)
COPY libs/common/pyproject.toml /build/libs/common/pyproject.toml
COPY libs/common/src /build/libs/common/src
COPY libs/contracts/pyproject.toml /build/libs/contracts/pyproject.toml
COPY libs/contracts/src /build/libs/contracts/src
COPY libs/messaging/pyproject.toml /build/libs/messaging/pyproject.toml
COPY libs/messaging/src /build/libs/messaging/src
COPY libs/observability/pyproject.toml /build/libs/observability/pyproject.toml
COPY libs/observability/src /build/libs/observability/src
COPY libs/storage/pyproject.toml /build/libs/storage/pyproject.toml
COPY libs/storage/src /build/libs/storage/src

COPY services/portfolio/pyproject.toml /build/services/portfolio/pyproject.toml
COPY services/portfolio/src /build/services/portfolio/src

# Non-editable install with uv cache mount for faster rebuilds
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /app/.venv && \
    uv pip install --python /app/.venv \
        /build/libs/common \
        /build/libs/contracts \
        /build/libs/messaging \
        /build/libs/observability \
        /build/libs/storage \
        /build/services/portfolio

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

RUN useradd --create-home --shell /bin/bash --uid 1001 appuser

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /build/services/portfolio/src /app/src
COPY services/portfolio/alembic /app/alembic
COPY services/portfolio/alembic.ini /app/alembic.ini
COPY infra/kafka/schemas /app/infra/kafka/schemas
# F-502 (QA iter-5): ship operational one-shots (backfills, re-syncs,
# repairs) into the image so SREs can run them via
# ``docker compose exec portfolio python /app/scripts/<name>.py`` rather
# than ``docker cp``-ing them onto every node every deploy. The scripts
# import ``portfolio.*`` modules directly — PYTHONPATH=/app/src below
# resolves them without further plumbing.
COPY services/portfolio/scripts /app/scripts

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/readyz')"

CMD ["uvicorn", "portfolio.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
