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
COPY libs/ml-clients/pyproject.toml /build/libs/ml-clients/pyproject.toml
COPY libs/ml-clients/src /build/libs/ml-clients/src
COPY libs/storage/pyproject.toml /build/libs/storage/pyproject.toml
COPY libs/storage/src /build/libs/storage/src
COPY libs/prompts/pyproject.toml /build/libs/prompts/pyproject.toml
COPY libs/prompts/src /build/libs/prompts/src

COPY services/knowledge-graph/pyproject.toml /build/services/knowledge-graph/pyproject.toml
COPY services/knowledge-graph/src /build/services/knowledge-graph/src

# Non-editable install with uv cache mount for faster rebuilds
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /app/.venv && \
    uv pip install --python /app/.venv \
        /build/libs/common \
        /build/libs/contracts \
        /build/libs/messaging \
        /build/libs/observability \
        /build/libs/ml-clients \
        /build/libs/storage \
        /build/libs/prompts \
        /build/services/knowledge-graph

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

RUN useradd --create-home --shell /bin/bash --uid 1001 appuser

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /build/services/knowledge-graph/src /app/src
COPY services/knowledge-graph/alembic /app/alembic
COPY services/knowledge-graph/alembic.ini /app/alembic.ini
COPY infra/kafka/schemas /app/infra/kafka/schemas

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8007

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8007/readyz')"

CMD ["uvicorn", "knowledge_graph.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8007"]
