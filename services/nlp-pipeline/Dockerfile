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

COPY services/nlp-pipeline/pyproject.toml /build/services/nlp-pipeline/pyproject.toml
COPY services/nlp-pipeline/src /build/services/nlp-pipeline/src

# Non-editable install with uv cache mount for faster rebuilds
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /app/.venv && \
    uv pip install --python /app/.venv \
        /build/libs/common \
        /build/libs/contracts \
        /build/libs/messaging \
        /build/libs/observability \
        "/build/libs/ml-clients[openai]" \
        /build/libs/storage \
        /build/libs/prompts \
        /build/services/nlp-pipeline

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

RUN useradd --create-home --shell /bin/bash --uid 1001 appuser

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /build/services/nlp-pipeline/src /app/src
COPY services/nlp-pipeline/alembic /app/alembic
COPY services/nlp-pipeline/alembic.ini /app/alembic.ini
COPY infra/kafka/schemas /app/infra/kafka/schemas

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8006

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8006/readyz')"

# Dev-only profiler — installed only when DEV=true (e.g. docker build --build-arg DEV=true)
ARG DEV=false
RUN if [ "$DEV" = "true" ]; then pip install py-spy==0.3.14; fi

CMD ["uvicorn", "nlp_pipeline.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8006"]
