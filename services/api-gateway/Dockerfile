# syntax=docker/dockerfile:1
# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir uv==0.4.29

# Copy only pyproject.toml + src from each lib (no tests, caches, venvs)
COPY libs/common/pyproject.toml /build/libs/common/pyproject.toml
COPY libs/common/src /build/libs/common/src
COPY libs/messaging/pyproject.toml /build/libs/messaging/pyproject.toml
COPY libs/messaging/src /build/libs/messaging/src
COPY libs/observability/pyproject.toml /build/libs/observability/pyproject.toml
COPY libs/observability/src /build/libs/observability/src

COPY services/api-gateway/pyproject.toml /build/services/api-gateway/pyproject.toml
COPY services/api-gateway/src /build/services/api-gateway/src

# Non-editable install with uv cache mount for faster rebuilds
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /app/.venv && \
    uv pip install --python /app/.venv \
        /build/libs/common \
        /build/libs/messaging \
        /build/libs/observability \
        /build/services/api-gateway

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

RUN useradd --create-home --shell /bin/bash --uid 1001 appuser

# Only the venv (self-contained) + service source + alembic
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /build/services/api-gateway/src /app/src
COPY services/api-gateway/alembic /app/alembic
COPY services/api-gateway/alembic.ini /app/alembic.ini

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/readyz')"

CMD ["uvicorn", "api_gateway.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
