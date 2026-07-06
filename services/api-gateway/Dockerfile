# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
# api-gateway (S9) — multi-stage build on worldview-python-base
#
# BUILDER stage uses worldview-python-base:latest which provides:
#   - Python 3.12-slim-bookworm
#   - uv 0.4.29
#   - Build/system deps (build-essential, libpq-dev, git, ...)
#   - Shared lib wheels in /wheels/ (common, contracts, messaging, ...)
#
# RUNTIME stage is a clean python:3.12-slim: it receives ONLY the built venv +
# the app source, so build-essential/git/libpq-dev never ship in the runtime
# image. This mirrors the other services' multi-stage pattern and drops the
# api-gateway image from ~956 MB (single-stage on the 715 MB base) to a slim
# runtime.  NOTE: api-gateway's deps (fastapi, httpx, pydantic, pyjwt[crypto],
# cryptography, cachetools, sse-starlette) are all pure-Python or self-contained
# manylinux wheels — no libpq/asyncpg — so python:3.12-slim needs no extra apt
# packages.  Runtime Python MUST stay 3.12 to match the venv's interpreter ABI.
#
# Build prereq:  `make python-base`  (or `make build-bases`).
# ─────────────────────────────────────────────────────────────────────────────

# ── Build stage ───────────────────────────────────────────────────────────────
FROM worldview-python-base:latest AS builder

USER root
WORKDIR /app

# Build into a relocatable venv (not --system) so the runtime stage can COPY it
# into a clean base without dragging the build toolchain along.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /app/.venv

# ── 1) Install shared libs from the pre-built wheel cache ─────────────────────
# Direct deps (pyproject.toml): `messaging`, `observability`. Transitive:
# `common` + `contracts`. uv resolves these via --find-links; third-party deps
# come from PyPI.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /app/.venv --find-links /wheels \
      common contracts messaging observability

# ── 2) Install service-local deps before source (maximises layer caching) ─────
COPY services/api-gateway/pyproject.toml /app/pyproject.toml

# Scaffold minimal package layout so hatchling can resolve sources at install
# time. Real source is copied in the runtime stage; the venv only needs the
# resolved dependency set (the app itself runs from PYTHONPATH=/app/src).
RUN mkdir -p /app/src/api_gateway && touch /app/src/api_gateway/__init__.py

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /app/.venv --find-links /wheels /app

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

RUN useradd --create-home --shell /bin/bash --uid 1001 appuser

# Copy only the built venv + real service source — no build tools, no git.
COPY --from=builder /app/.venv /app/.venv
COPY --chown=appuser:appuser services/api-gateway/src /app/src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/readyz')"

CMD ["uvicorn", "api_gateway.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
