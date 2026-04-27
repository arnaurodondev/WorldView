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

COPY services/content-store/pyproject.toml /build/services/content-store/pyproject.toml
COPY services/content-store/src /build/services/content-store/src

# Non-editable install with uv cache mount for faster rebuilds
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /app/.venv && \
    uv pip install --python /app/.venv \
        /build/libs/common \
        /build/libs/contracts \
        /build/libs/messaging \
        /build/libs/observability \
        /build/libs/storage \
        /build/services/content-store

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

RUN useradd --create-home --shell /bin/bash --uid 1001 appuser

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /build/services/content-store/src /app/src
COPY services/content-store/alembic /app/alembic
COPY services/content-store/alembic.ini /app/alembic.ini
COPY infra/kafka/schemas /app/infra/kafka/schemas

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8005

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8005/readyz')"

CMD ["uvicorn", "content_store.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8005"]
