# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
# worldview-python-base
#
# Shared base image for all 10 Python services. Bakes in:
#   - Python 3.12-slim-bookworm (unified — previously services used 3.11 and
#     intelligence-migrations used 3.12; standardise on the newer)
#   - uv 0.4.29 (dependency installer)
#   - System packages common to every service (asyncpg build deps, libpq,
#     postgresql-client, curl, ca-certificates, git)
#   - The 8 shared worldview libs pre-built as wheels in /wheels/
#   - A non-root `worldview` user (uid 1000)
#
# Services consume this image with:
#   FROM worldview-python-base:latest
#   RUN uv pip install --system --find-links /wheels <lib_names> <service>
#
# Build with:
#   docker build -f infra/docker/python-base/Dockerfile -t worldview-python-base:latest .
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS python-base

SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# Avoid interactive prompts during apt operations.
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ── System packages ────────────────────────────────────────────────────────────
# build-essential + libpq-dev: needed at build time by asyncpg/psycopg native ext.
# libpq5:                       runtime postgres client lib.
# postgresql-client:            psql binary for migration containers.
# curl/ca-certificates/git:     health probes, model downloads, pip-from-git.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential \
      libpq-dev \
      libpq5 \
      postgresql-client \
      curl \
      ca-certificates \
      git \
    && rm -rf /var/lib/apt/lists/*

# ── uv installer (pinned) ──────────────────────────────────────────────────────
RUN pip install --no-cache-dir uv==0.4.29

# ── Non-root service user (uid 1000 for predictable bind-mount perms) ──────────
RUN useradd -m -u 1000 -s /bin/bash worldview

# ── Wheel cache directory (will hold pre-built shared lib wheels) ──────────────
RUN mkdir -p /wheels && chown worldview:worldview /wheels

# ── Stage 1: build the 8 shared libs into wheels ───────────────────────────────
# We copy each lib's pyproject.toml + src tree (the only inputs hatchling needs)
# into a build scratch dir, then iterate `uv build --wheel` per lib. Build order
# follows the internal dep graph:
#   observability ← messaging ← ml-clients
#   (common, contracts, storage, prompts, tools are independent)
# Note: `uv build` does not require deps to be installed — wheels are pure
# packaging, the consuming service installs and resolves deps at install time.
WORKDIR /build

COPY libs/common/pyproject.toml        /build/libs/common/pyproject.toml
COPY libs/common/src                   /build/libs/common/src
COPY libs/contracts/pyproject.toml     /build/libs/contracts/pyproject.toml
COPY libs/contracts/src                /build/libs/contracts/src
COPY libs/observability/pyproject.toml /build/libs/observability/pyproject.toml
COPY libs/observability/src            /build/libs/observability/src
COPY libs/messaging/pyproject.toml     /build/libs/messaging/pyproject.toml
COPY libs/messaging/src                /build/libs/messaging/src
COPY libs/storage/pyproject.toml       /build/libs/storage/pyproject.toml
COPY libs/storage/src                  /build/libs/storage/src
COPY libs/ml-clients/pyproject.toml    /build/libs/ml-clients/pyproject.toml
COPY libs/ml-clients/src               /build/libs/ml-clients/src
COPY libs/prompts/pyproject.toml       /build/libs/prompts/pyproject.toml
COPY libs/prompts/src                  /build/libs/prompts/src
COPY libs/tools/pyproject.toml         /build/libs/tools/pyproject.toml
COPY libs/tools/src                    /build/libs/tools/src

# Build all wheels. We don't use `--mount=type=cache` for uv here because wheels
# must be persisted into the final image layer.
RUN for lib in common contracts observability messaging storage ml-clients prompts tools; do \
      echo "── Building wheel for $lib ──" && \
      uv build --wheel --out-dir /wheels /build/libs/$lib ; \
    done && \
    ls -la /wheels && \
    chown -R worldview:worldview /wheels

# ── Final image cleanup ────────────────────────────────────────────────────────
# Drop the /build scratch dir — services don't need source, only the wheels.
RUN rm -rf /build

WORKDIR /app
USER worldview

# Image users do NOT install the wheels here. Each service's Dockerfile picks
# the subset it needs via e.g.:
#   RUN uv pip install --system --find-links /wheels \
#       common contracts messaging observability
# This keeps the base image generic.
