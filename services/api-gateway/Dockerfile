# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
# api-gateway (S9) — pilot for worldview-python-base migration
#
# Builds on top of worldview-python-base:latest which already provides:
#   - Python 3.12-slim-bookworm
#   - uv 0.4.29
#   - System deps (build-essential, libpq, postgresql-client, curl, ...)
#   - Non-root `worldview` user (uid 1000)
#   - Shared lib wheels in /wheels/ (common, contracts, messaging,
#     observability, storage, ml-clients, prompts, tools)
#
# Build prereq:  `make python-base`  (or `make build-bases`).
# ─────────────────────────────────────────────────────────────────────────────
FROM worldview-python-base:latest AS runtime

USER root
WORKDIR /app

# ── 1) Install shared libs we need from the pre-built wheel cache ─────────────
# Direct deps (pyproject.toml): `messaging`, `observability`.
# Transitive deps consumed at runtime: `common` (UUIDv7, time helpers) and
# `contracts` (canonical Pydantic models). uv resolves these via --find-links.
# Third-party deps (confluent-kafka, structlog, OTEL, ...) are pulled from PyPI.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --find-links /wheels \
      common contracts messaging observability

# ── 2) Install service-local deps before source (maximises layer caching) ─────
COPY services/api-gateway/pyproject.toml /app/pyproject.toml

# Scaffold minimal package layout so hatchling can resolve sources at install
# time. Real source is copied in step 3.
RUN mkdir -p /app/src/api_gateway && touch /app/src/api_gateway/__init__.py

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --find-links /wheels /app

# ── 3) Copy real service source on top of the scaffold ────────────────────────
COPY --chown=worldview:worldview services/api-gateway/src /app/src

# ── Environment ────────────────────────────────────────────────────────────────
ENV PYTHONPATH="/app/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER worldview
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/readyz')"

CMD ["uvicorn", "api_gateway.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
