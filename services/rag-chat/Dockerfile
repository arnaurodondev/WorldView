# syntax=docker/dockerfile:1
# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir uv==0.4.29

# Cache-bust for the shared-lib COPY layers below.
#
# WHY: BuildKit's `local` build-context source op is content/metadata-addressed
# and is NOT invalidated by `docker build --no-cache` (that flag only re-runs
# RUN/COPY ops, it does not re-snapshot the local source those ops read from).
# When an edited file under libs/<x>/src happened to present metadata (size +
# mtime + inode) matching a prior snapshot, BuildKit fed the `COPY libs/<x>/src`
# layer a STALE snapshot while genuinely-changed services/rag-chat/src was
# re-transferred — silently shipping old shared-lib code (notably libs/prompts:
# the container kept serving an old synthesis-prompt version after a rebuild).
# See docs/audits/2026-06-27-compose-build-stale-prompts.md.
#
# Changing CACHE_BUST forces this RUN (and therefore every COPY below it) to
# re-resolve the local source, defeating the stale dedup. scripts/rebuild_service.sh
# passes a per-commit/per-worktree value; the default `unset` keeps plain
# `docker build` behaviour unchanged.
ARG CACHE_BUST=unset
RUN echo "cache-bust=${CACHE_BUST}"

# Copy only pyproject.toml + src from each lib (no tests, caches, venvs)
COPY libs/common/pyproject.toml /build/libs/common/pyproject.toml
COPY libs/common/src /build/libs/common/src
COPY libs/messaging/pyproject.toml /build/libs/messaging/pyproject.toml
COPY libs/messaging/src /build/libs/messaging/src
COPY libs/observability/pyproject.toml /build/libs/observability/pyproject.toml
COPY libs/observability/src /build/libs/observability/src
COPY libs/ml-clients/pyproject.toml /build/libs/ml-clients/pyproject.toml
COPY libs/ml-clients/src /build/libs/ml-clients/src
COPY libs/prompts/pyproject.toml /build/libs/prompts/pyproject.toml
COPY libs/prompts/src /build/libs/prompts/src
COPY libs/contracts/pyproject.toml /build/libs/contracts/pyproject.toml
COPY libs/contracts/src /build/libs/contracts/src
COPY libs/tools/pyproject.toml /build/libs/tools/pyproject.toml
COPY libs/tools/src /build/libs/tools/src

COPY services/rag-chat/pyproject.toml /build/services/rag-chat/pyproject.toml
COPY services/rag-chat/src /build/services/rag-chat/src

# Non-editable install with uv cache mount for faster rebuilds
# BP-181: all libs (including libs/tools) must be listed here — missing lib
# causes ModuleNotFoundError at startup
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /app/.venv && \
    uv pip install --python /app/.venv \
        /build/libs/common \
        /build/libs/messaging \
        /build/libs/observability \
        /build/libs/ml-clients \
        /build/libs/prompts \
        /build/libs/contracts \
        /build/libs/tools \
        /build/services/rag-chat

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

RUN useradd --create-home --shell /bin/bash --uid 1001 appuser

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /build/services/rag-chat/src /app/src
COPY services/rag-chat/alembic /app/alembic
COPY services/rag-chat/alembic.ini /app/alembic.ini

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8008

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8008/readyz')"

# Dev-only profiler — installed only when DEV=true (e.g. docker build --build-arg DEV=true)
ARG DEV=false
RUN if [ "$DEV" = "true" ]; then pip install py-spy==0.3.14; fi

CMD ["uvicorn", "rag_chat.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8008"]
