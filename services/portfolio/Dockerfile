# syntax=docker/dockerfile:1
# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir uv==0.4.29

# ── 1) Shared libs FIRST — COPY sources + install into the venv. ──────────────
# Libs change rarely, so keeping them in their own layer means an app-code edit
# below does NOT bust this expensive multi-lib install. Copy only pyproject.toml
# + src from each lib (no tests, caches, venvs).
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

RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /app/.venv && \
    uv pip install --python /app/.venv \
        /build/libs/common \
        /build/libs/contracts \
        /build/libs/messaging \
        /build/libs/observability \
        /build/libs/storage

# ── 2) Service source LAST — COPY + install on top of the cached lib layer. ────
# Editing services/portfolio/src only re-runs this small install; the shared
# libs above (already satisfying the bare `common`/`contracts`/… requirements)
# stay cached, so only the service's own third-party deps are (re)resolved.
COPY services/portfolio/pyproject.toml /build/services/portfolio/pyproject.toml
COPY services/portfolio/src /build/services/portfolio/src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /app/.venv /build/services/portfolio

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

# Port 8001 is the portfolio (S1) convention across the platform: config.py default
# (port: int = 8001), the k8s Service, and every inter-service client
# (RAG_CHAT_S1_BASE_URL, alert's S1 health client, api-gateway's S1 route) all use
# 8001. The CMD previously hardcoded --port 8000, so the container bound 8000 while
# everything dialed 8001 → alert/rag-chat health checks to portfolio timed out and the
# probe (also 8001) refused. Bind 8001 to match.
EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/readyz')"

CMD ["uvicorn", "portfolio.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8001"]
