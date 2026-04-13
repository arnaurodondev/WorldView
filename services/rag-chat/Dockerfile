# syntax=docker/dockerfile:1
# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir uv==0.4.29

COPY libs/common /build/libs/common
COPY libs/messaging /build/libs/messaging
COPY libs/observability /build/libs/observability
COPY services/rag-chat /build/services/rag-chat

RUN uv venv /app/.venv && \
    uv pip install --no-cache --python /app/.venv \
        -e /build/libs/common \
        -e /build/libs/messaging \
        -e /build/libs/observability \
        -e /build/services/rag-chat

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

RUN useradd --create-home --shell /bin/bash --uid 1001 appuser

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /build/libs /app/libs
COPY --from=builder /build/services/rag-chat/src /app/src
COPY --from=builder /build/services/rag-chat/alembic /app/alembic
COPY --from=builder /build/services/rag-chat/alembic.ini /app/alembic.ini

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src:/app/libs/common/src:/app/libs/messaging/src:/app/libs/observability/src"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8008

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8008/readyz')"

CMD ["uvicorn", "rag_chat.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8008"]
