# syntax=docker/dockerfile:1
# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build tools
RUN pip install --no-cache-dir uv==0.4.29

# Copy shared libs and service source
COPY libs/common /build/libs/common
COPY libs/contracts /build/libs/contracts
COPY libs/messaging /build/libs/messaging
COPY libs/observability /build/libs/observability
COPY libs/storage /build/libs/storage
COPY services/content-ingestion /build/services/content-ingestion

# Install all dependencies into /app/.venv so shebang paths match the runtime stage
RUN uv venv /app/.venv && \
    uv pip install --no-cache --python /app/.venv \
        -e /build/libs/common \
        -e /build/libs/contracts \
        -e /build/libs/messaging \
        -e /build/libs/observability \
        -e /build/libs/storage \
        -e /build/services/content-ingestion

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Create non-root user
RUN useradd --create-home --shell /bin/bash --uid 1001 appuser

# Copy installed packages from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /build/libs /app/libs
COPY --from=builder /build/services/content-ingestion/src /app/src
COPY --from=builder /build/services/content-ingestion/alembic /app/alembic
COPY --from=builder /build/services/content-ingestion/alembic.ini /app/alembic.ini

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src:/app/libs/common/src:/app/libs/contracts/src:/app/libs/messaging/src:/app/libs/observability/src:/app/libs/storage/src"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8004

# Healthcheck against the readyz endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8004/readyz')"

CMD ["uvicorn", "content_ingestion.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8004"]
