# Investigation Report: Dockerfile Optimization — Size & Build Cache

**Date**: 2026-04-27
**Investigator**: Claude (investigation skill)
**Severity**: MEDIUM (performance / developer-experience, no runtime correctness issue)
**Status**: Root causes identified — 7 optimization findings, 3 critical

---

## 1. Issue Summary

Platform Dockerfiles were audited for two objectives: (1) reducing final container image size by eliminating files not needed at runtime, and (2) improving build speed by maximizing Docker layer cache utilization. The investigation covers all 12 Dockerfiles across 10 Python services, 1 Next.js frontend, and 2 infrastructure images.

---

## 2. Current State — Image Sizes

| Image | Size | Category |
|-------|------|----------|
| worldview-postgres | 3.68 GB | infra (AGE compile) |
| worldview-content-store | 1.40 GB | service |
| worldview-market-ingestion | 1.33 GB | service |
| worldview-nlp-pipeline | 1.28 GB | service |
| worldview-gliner-server | 1.28 GB | infra (PyTorch) |
| worldview-knowledge-graph | 1.21 GB | service |
| worldview-content-ingestion | 1.15 GB | service |
| worldview-market-data | 1.15 GB | service |
| worldview-portfolio | 1.15 GB | service |
| worldview-rag-chat | 736 MB | service |
| worldview-alert | 662 MB | service |
| worldview-api-gateway | 627 MB | service |
| worldview-intelligence-migrations | 363 MB | migration |
| worldview-web | 280 MB | frontend |

**Total disk footprint (production images only)**: ~13.2 GB

Each service has 3–7 container variants (api, consumers, dispatcher, scheduler, migrate) all sharing the same base image, so disk deduplication helps — but the base is too large.

---

## 3. Evidence Collected

| # | Evidence | Source | Relevance |
|---|----------|--------|-----------|
| E-1 | `COPY /build/libs /app/libs` is 231–635 MB per image | `docker history` on api-gateway, content-store, knowledge-graph | CRITICAL: single largest bloat source |
| E-2 | api-gateway container has `.mypy_cache/` (40+46 MB), `.venv/` (134 MB), `tests/`, `.pytest_cache/` inside `/app/libs/` | `docker run --rm worldview-api-gateway find ...` | Confirms non-runtime files in production |
| E-3 | knowledge-graph container has 609 MB of junk in `/app/libs/` | `docker run --rm worldview-knowledge-graph du ...` | Largest waste case |
| E-4 | `libs/contracts/.venv/` = 293 MB, `libs/observability/.venv/` = 133 MB on host | `du -sh` | Local dev venvs shipped into every image |
| E-5 | No root `.dockerignore` — build context is ~6.5 GB | `du -sh` per top-level dir | Build context transfer wastes time |
| E-6 | Build context = repo root (`../..`) for all services | `docker-compose.yml` grep | Confirms E-5 impact |
| E-7 | All libs + service source copied in a single COPY → no dependency layer caching | Dockerfile review | Any code change triggers full reinstall |
| E-8 | Editable installs (`-e`) used but PYTHONPATH overrides resolution anyway | Dockerfile review | Redundant mechanism |

---

## 4. Findings

### F-1 (CRITICAL): `COPY /build/libs /app/libs` ships dev artifacts into production

**Every Python service Dockerfile** copies the entire `/build/libs` directory from the builder stage to runtime. This directory contains:

| Artifact | Size (on host) | Needed at runtime? |
|----------|----------------|--------------------|
| `libs/contracts/.venv/` | 293 MB | NO |
| `libs/observability/.venv/` | 133 MB | NO |
| `libs/ml-clients/.mypy_cache/` | 48 MB | NO |
| `libs/messaging/.mypy_cache/` | 45 MB | NO |
| `libs/common/.mypy_cache/` | 39 MB | NO |
| `libs/contracts/.mypy_cache/` | 31 MB | NO |
| `libs/prompts/.mypy_cache/` | 6.8 MB | NO |
| `libs/messaging/.pytest_cache/` | 36 KB | NO |
| `libs/ml-clients/.pytest_cache/` | 32 KB | NO |
| All `libs/*/tests/` | ~2.3 MB | NO |
| `IMPLEMENTATION.md`, `README.md`, `uv.lock` | ~92 KB | NO |
| **Total unnecessary** | **~598 MB** | |

Only `libs/*/src/` is needed at runtime (for the PYTHONPATH resolution).

**Measured per-image waste:**
- knowledge-graph: 635 MB libs layer, ~609 MB is junk → **96% waste**
- content-store: 575 MB libs layer, ~570 MB is junk → **99% waste**
- api-gateway: 231 MB libs layer, ~221 MB is junk → **96% waste**

### F-2 (CRITICAL): No root `.dockerignore` — 6.5 GB build context

Build context is the repo root (`context: ../..`). Without a `.dockerignore`, Docker sends everything:

| Directory | Size | Needed by COPY? |
|-----------|------|-----------------|
| `.claude/` | 968 MB | NO |
| `apps/` | 554 MB | NO (for Python services) |
| `docs/` | 408 MB | NO |
| `.git/` | 66 MB | NO |
| Service `.mypy_cache/` dirs | ~1.3 GB | NO |
| Service `tests/` dirs | ~58 MB | NO |

Estimated build context size: **~6.5 GB** sent to daemon per build. Only ~50 MB is actually used.

### F-3 (CRITICAL): No dependency layer caching — full reinstall on every code change

Current pattern:
```dockerfile
COPY libs/common /build/libs/common        # <-- copies pyproject.toml AND source
COPY services/market-data /build/services/market-data
RUN uv pip install -e ...                  # <-- invalidated by ANY file change above
```

A one-line change in any lib's `.py` file invalidates the entire `uv pip install` layer, triggering a full download + compile of all dependencies. This typically takes 30–90 seconds.

Additionally, `--no-cache` is used, explicitly disabling uv's package download cache.

### F-4 (MEDIUM): Editable installs (`-e`) are unnecessary and counterproductive

All services use `-e` (editable) mode. In the runtime stage, packages are found via the manual `PYTHONPATH` env var pointing to each `libs/*/src/` directory, not through pip's editable `.egg-link` mechanism.

With non-editable installs (`uv pip install /build/libs/common` without `-e`), all library code would be installed into `.venv/lib/python3.11/site-packages/`. This means:
- No need to COPY `/build/libs` to runtime at all
- PYTHONPATH only needs the service `src/` directory
- The `.venv` is fully self-contained

### F-5 (LOW): Service tests/caches copied to builder stage unnecessarily

`COPY services/<name> /build/services/<name>` copies entire service directories including `.mypy_cache/` (41–182 MB each), `tests/` (up to 9.7 MB), `.pytest_cache/`. These aren't propagated to runtime (selective COPY of `src/`, `alembic/`, `alembic.ini`), but they bloat the builder layer and slow the COPY step.

### F-6 (LOW): Python version inconsistency

Services use `python:3.11-slim`, while `intelligence-migrations` and `gliner` use `python:3.12-slim`. This prevents base layer sharing between the two groups.

### F-7 (INFO): worldview-web is already well-optimized

The Next.js Dockerfile uses proper multi-stage (deps → builder → runner), has a `.dockerignore`, uses standalone output mode, and produces a 280 MB image. No changes recommended.

---

## 5. Impact Analysis

### Size reduction estimate

| Image | Current | Estimated After F-1+F-4 | Savings |
|-------|---------|------------------------|---------|
| knowledge-graph | 1.21 GB | ~500 MB | -710 MB (59%) |
| content-store | 1.40 GB | ~730 MB | -670 MB (48%) |
| market-ingestion | 1.33 GB | ~730 MB | -600 MB (45%) |
| content-ingestion | 1.15 GB | ~550 MB | -600 MB (52%) |
| market-data | 1.15 GB | ~550 MB | -600 MB (52%) |
| nlp-pipeline | 1.28 GB | ~680 MB | -600 MB (47%) |
| portfolio | 1.15 GB | ~550 MB | -600 MB (52%) |
| rag-chat | 736 MB | ~350 MB | -386 MB (52%) |
| alert | 662 MB | ~440 MB | -222 MB (34%) |
| api-gateway | 627 MB | ~400 MB | -227 MB (36%) |

**Total estimated savings across 10 services: ~5.2 GB (from 10.7 GB to ~5.5 GB)**

### Build time reduction estimate

| Optimization | Estimated savings |
|-------------|-------------------|
| F-2: `.dockerignore` (6.5 GB → ~50 MB context) | 10–30s per build (context transfer) |
| F-3: Dependency layer caching | 30–90s per code-only change |
| F-5: Exclude tests/caches from builder COPY | 5–15s per build (COPY step) |

---

## 6. Recommended Fix — Optimized Dockerfile Template

The following template addresses F-1, F-3, F-4, and F-5 simultaneously:

```dockerfile
# syntax=docker/dockerfile:1

# ── Stage 1: dependency install (cached unless pyproject.toml changes) ─────────
FROM python:3.11-slim AS deps

WORKDIR /build
RUN pip install --no-cache-dir uv==0.4.29

# Copy ONLY dependency specifications (pyproject.toml) — not source code.
# This layer is cached as long as dependencies don't change.
COPY libs/common/pyproject.toml /build/libs/common/pyproject.toml
COPY libs/contracts/pyproject.toml /build/libs/contracts/pyproject.toml
COPY libs/messaging/pyproject.toml /build/libs/messaging/pyproject.toml
COPY libs/observability/pyproject.toml /build/libs/observability/pyproject.toml
COPY libs/storage/pyproject.toml /build/libs/storage/pyproject.toml
COPY services/<SERVICE>/pyproject.toml /build/services/<SERVICE>/pyproject.toml

# Scaffold minimal package structure so uv can resolve local deps.
# (uv needs at least an __init__.py for each package referenced by pyproject.toml)
RUN mkdir -p /build/libs/common/src/common && touch /build/libs/common/src/common/__init__.py && \
    mkdir -p /build/libs/contracts/src/contracts && touch /build/libs/contracts/src/contracts/__init__.py && \
    mkdir -p /build/libs/messaging/src/messaging && touch /build/libs/messaging/src/messaging/__init__.py && \
    mkdir -p /build/libs/observability/src/observability && touch /build/libs/observability/src/observability/__init__.py && \
    mkdir -p /build/libs/storage/src/storage && touch /build/libs/storage/src/storage/__init__.py && \
    mkdir -p /build/services/<SERVICE>/src/<SERVICE_PKG> && touch /build/services/<SERVICE>/src/<SERVICE_PKG>/__init__.py

# Install all dependencies. This layer is cached across code-only rebuilds.
# Use uv cache mount to avoid re-downloading packages.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /app/.venv && \
    uv pip install --python /app/.venv \
        /build/libs/common \
        /build/libs/contracts \
        /build/libs/messaging \
        /build/libs/observability \
        /build/libs/storage \
        /build/services/<SERVICE>

# ── Stage 2: copy source (this layer changes on every code edit) ──────────────
FROM deps AS builder

# Now copy actual source code (overwriting the scaffold __init__.py files).
COPY libs/common/src /build/libs/common/src
COPY libs/contracts/src /build/libs/contracts/src
COPY libs/messaging/src /build/libs/messaging/src
COPY libs/observability/src /build/libs/observability/src
COPY libs/storage/src /build/libs/storage/src
COPY services/<SERVICE>/src /build/services/<SERVICE>/src
COPY services/<SERVICE>/alembic /build/services/<SERVICE>/alembic
COPY services/<SERVICE>/alembic.ini /build/services/<SERVICE>/alembic.ini
COPY infra/kafka/schemas /build/infra/kafka/schemas

# Re-install in non-editable mode with source present (fast — deps already cached).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /app/.venv \
        /build/libs/common \
        /build/libs/contracts \
        /build/libs/messaging \
        /build/libs/observability \
        /build/libs/storage \
        /build/services/<SERVICE>

# ── Stage 3: minimal runtime ─────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app
RUN useradd --create-home --shell /bin/bash --uid 1001 appuser

# Only the venv (self-contained with all libs installed), service source, and alembic.
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /build/services/<SERVICE>/src /app/src
COPY --from=builder /build/services/<SERVICE>/alembic /app/alembic
COPY --from=builder /build/services/<SERVICE>/alembic.ini /app/alembic.ini
COPY --from=builder /build/infra/kafka/schemas /app/infra/kafka/schemas

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

USER appuser
EXPOSE <PORT>

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:<PORT>/readyz')"

CMD ["uvicorn", "<SERVICE_PKG>.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "<PORT>"]
```

### Root `.dockerignore` (F-2)

```
# Development artifacts
**/.mypy_cache
**/.pytest_cache
**/__pycache__
**/.venv
**/node_modules
**/.next

# IDE/editor
.vscode
.idea
*.swp

# Documentation and config (not needed for builds)
.claude/
.claire/
docs/
*.md
!services/*/alembic.ini

# Git
.git
.gitignore

# Tests (not needed for production images)
**/tests/
**/test_*.py

# Frontend (not needed for Python service builds)
apps/

# Misc
*.pyc
*.pyo
.env*
```

**Note**: The `.dockerignore` applies to ALL builds from this context. The `worldview-web` Dockerfile uses its own build context (`apps/worldview-web/`) with its own `.dockerignore`, so it is unaffected.

---

## 7. Per-Dockerfile Specific Notes

### intelligence-migrations
- Single-stage build (fine for migration-only container)
- Uses `pip` instead of `uv` — could be aligned but low priority
- Uses `python:3.12-slim` — align to `3.11-slim` if standardizing

### infra/gliner
- Comment says "Pre-download the model into the image layer" but no `RUN` actually downloads it
- `libgomp1` is needed for PyTorch — correctly kept
- Consider adding `RUN python -c "from gliner import GLiNER; GLiNER.from_pretrained('${GLINER_MODEL_PATH}')"` to actually bake the model into the image layer

### infra/postgres
- Already optimized — `apk del .build-deps` cleans build tools after AGE compilation
- The 3.68 GB size is dominated by TimescaleDB + pgvector + AGE extensions; not much to trim

### apps/worldview-web
- Already the best-optimized Dockerfile in the repo (3-stage, standalone output, .dockerignore)
- No changes needed

---

## 8. Open Questions

1. **Will non-editable installs break PYTHONPATH resolution?** — Need to verify that `uv pip install` (non-editable) for local packages puts source into `site-packages/` correctly. The service `src/` still needs PYTHONPATH since it's not installed as a package via pip.
2. **Shared base image?** — A common `worldview-base:latest` image with the venv pre-populated with shared libs could avoid reinstalling the same 5–7 libs across 10 services. This is a more advanced optimization.
3. **Docker Compose `cache_from`** — Could be configured to reuse layers from a registry for CI builds. Out of scope for local dev but valuable for CI/CD.

---

## 9. Priority Order for Implementation

| Priority | Finding | Effort | Impact |
|----------|---------|--------|--------|
| **P0** | F-2: Add root `.dockerignore` | 5 min | Cuts context from 6.5 GB to ~50 MB |
| **P1** | F-1 + F-4: Non-editable installs + selective COPY (eliminate libs in runtime) | 30 min per service | Saves 200–600 MB per image |
| **P2** | F-3: Separate dependency layer caching | Part of P1 template | Saves 30–90s on code-only rebuilds |
| **P3** | F-5: Selective COPY in builder (exclude tests/caches) | 10 min per service | Faster COPY in builder |
| **P4** | F-6: Align Python versions | 5 min | Minor — base layer sharing |

---

## Appendix A — `worldview-python-base` shared base image (2026-06-08)

Resolves Open Question #2 (§8) and supersedes the per-service template in §6
for the lib-install layer. The base image is built once and provides:

- `python:3.12-slim-bookworm` (unifies F-6)
- `uv==0.4.29`
- System packages: `build-essential`, `libpq-dev`, `libpq5`,
  `postgresql-client`, `curl`, `ca-certificates`, `git`
- Non-root user `worldview` (uid 1000)
- All 8 shared libs pre-built as wheels in `/wheels/`
  (`common`, `contracts`, `messaging`, `observability`, `storage`,
  `ml-clients`, `prompts`, `tools`)

Build:
```
make python-base    # or: make build-bases
```

Then each service Dockerfile reduces to ~20 LOC:
```dockerfile
FROM worldview-python-base:latest
USER root
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --find-links /wheels \
      <lib subset for this service>
COPY services/<svc>/pyproject.toml /app/pyproject.toml
RUN mkdir -p /app/src/<svc_pkg> && touch /app/src/<svc_pkg>/__init__.py
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --find-links /wheels /app
COPY --chown=worldview:worldview services/<svc>/src /app/src
# COPY <alembic / scripts / kafka schemas> as needed
ENV PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER worldview
EXPOSE <port>
HEALTHCHECK ...
CMD ["uvicorn", "<svc_pkg>.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "<port>"]
```

### Migration order + per-service lib subset

Listed in recommended migration order (lowest-risk → highest-risk).

| # | Service | Port | Lib subset (`uv pip install`) | Extra COPY | Notes |
|---|---------|------|-------------------------------|------------|-------|
| 0 | **api-gateway** *(pilot — DONE)* | 8000 | common contracts messaging observability | — | Stateless; no Alembic. |
| 1 | content-store | 8005 | common contracts messaging observability storage | alembic/ alembic.ini infra/kafka/schemas | Standard CRUD service. |
| 2 | content-ingestion | varies | common contracts messaging observability storage | alembic/ alembic.ini infra/kafka/schemas | Mirrors content-store deps. |
| 3 | market-data | varies | common contracts messaging observability storage | alembic/ alembic.ini infra/kafka/schemas | Standard. |
| 4 | market-ingestion | 8002 | common contracts messaging observability storage | alembic/ alembic.ini infra/kafka/schemas | Standard. |
| 5 | portfolio | 8000 | common contracts messaging observability storage | alembic/ alembic.ini infra/kafka/schemas + **services/portfolio/scripts** | F-502 op-scripts COPY. |
| 6 | alert | varies | common contracts messaging observability storage | alembic/ alembic.ini infra/kafka/schemas | Standard. |
| 7 | knowledge-graph | varies | common contracts messaging observability storage prompts | alembic/ alembic.ini infra/kafka/schemas | Adds `prompts` lib for LLM templates. |
| 8 | nlp-pipeline | 8006 | common contracts messaging observability storage `ml-clients[openai]` prompts | alembic/ alembic.ini infra/kafka/schemas | Needs `ml-clients[openai]` extra. |
| 9 | rag-chat | 8008 | common contracts messaging observability ml-clients prompts tools | alembic/ alembic.ini | All 7 non-storage libs. |
| 10 | intelligence-migrations | n/a | (none — requirements.txt only) | alembic/ alembic.ini seeds/ scripts/ entrypoint.sh | Currently uses `requirements.txt`+`pip`. Can adopt base image just for the system deps + Python 3.12 unification; keep `pip install -r requirements.txt`. |

### Validation per service

After migrating each service:
```
make python-base
DOCKER_BUILDKIT=1 docker compose -f infra/compose/docker-compose.yml build --no-cache <service>
docker compose up -d --no-deps --force-recreate <service>
sleep 8 && curl -s http://localhost:<port>/healthz
```

### Known caveats

- **Image size up, build time down**: the base image is 715 MB (vs 396 MB
  legacy api-gateway runtime). However, the 715 MB layer is **shared across
  all 10 service images** on disk (Docker deduplicates layers), so total disk
  footprint drops once ≥2 services have migrated.
- **`ml-clients` optional extras**: services that need `[openai]` etc. must
  install the extra explicitly via PyPI in their service Dockerfile (the
  wheel in /wheels is the bare `ml-clients` package; extras pull from PyPI).
- **Python 3.11 → 3.12**: all services declare `requires-python = ">=3.11,<3.13"`
  in pyproject.toml so 3.12 is in-range. Watch for any third-party deps that
  pin to 3.11 at install time.
- **`make python-base` must run before `docker compose build`** for any
  migrated service. Add to CI build job before image builds.

