# syntax=docker/dockerfile:1
# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir uv==0.4.29

COPY libs/common /build/libs/common
COPY libs/contracts /build/libs/contracts
COPY libs/messaging /build/libs/messaging
COPY libs/observability /build/libs/observability
COPY libs/storage /build/libs/storage
COPY services/content-store /build/services/content-store

RUN uv venv /app/.venv && \
    uv pip install --no-cache --python /app/.venv \
        -e /build/libs/common \
        -e /build/libs/contracts \
        -e /build/libs/messaging \
        -e /build/libs/observability \
        -e /build/libs/storage \
        -e /build/services/content-store

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

RUN useradd --create-home --shell /bin/bash --uid 1001 appuser

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /build/libs /app/libs
COPY --from=builder /build/services/content-store/src /app/src
COPY --from=builder /build/services/content-store/alembic /app/alembic
COPY --from=builder /build/services/content-store/alembic.ini /app/alembic.ini

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src:/app/libs/common/src:/app/libs/contracts/src:/app/libs/messaging/src:/app/libs/observability/src:/app/libs/storage/src"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8005

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8005/readyz')"

CMD ["uvicorn", "content_store.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8005"]
