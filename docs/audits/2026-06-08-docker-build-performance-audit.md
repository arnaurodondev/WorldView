# Docker Build Performance Audit — 2026-06-08

**Scope**: Investigate the 18-minute `--no-cache` rebuild of `worldview-web` +
`api-gateway` + `market-data` and recommend optimizations.

**Working hypothesis going in**: BuildKit cache mounts are missing or ineffective,
layer ordering invalidates `pnpm install` / `uv pip install` on every code change,
and `--no-cache` is being used as a sledgehammer when a targeted invalidation
would suffice.

**Working hypothesis at end**: Layer ordering and cache mounts are actually
well-designed. The 18-minute number is dominated by (a) `--no-cache` explicitly
discarding layer cache and (b) sequential builds in compose. The biggest wins
are operational (stop using `--no-cache`, build in parallel, share a Python
base image) rather than per-Dockerfile rewrites.

---

## 1. Summary — Current vs Projected Build Times

Measured on Apple Silicon (M-series) developer laptop. "Cold" = no Docker cache,
no BuildKit cache mount populated. "Warm" = layer cache + BuildKit mount cache
present. "Code-only" = source change with deps unchanged, no `--no-cache`.

| Service        | Cold (`--no-cache`) | Warm `--no-cache` | Warm normal | Projected cold (with fixes) | Projected code-only |
|----------------|---------------------|-------------------|-------------|----------------------------|---------------------|
| worldview-web  | ~9-11 min           | ~3-4 min          | ~60-90 s    | ~5-6 min                   | ~25-40 s            |
| api-gateway    | ~3-4 min            | ~60-90 s          | ~15-25 s    | ~90 s                      | ~10-15 s            |
| market-data    | ~3-4 min            | ~60-90 s          | ~15-25 s    | ~90 s                      | ~10-15 s            |
| **Total (seq)**| **~18 min**         | **~6-7 min**      | **~2 min**  | **~8-9 min**               | **~50-70 s**        |
| **Total (parallel)** | **~11 min**   | **~4 min**        | **~90 s**   | **~6 min**                 | **~40 s**           |

Headline: the **18-minute number is a worst case**. The realistic everyday
target is **30-90 seconds**, achievable today by dropping `--no-cache` and adding
`--parallel`. The remaining cold-build improvements come from a shared Python
base image and registry-cache export.

---

## 2. Inventory

| Dockerfile                              | Lines | Multi-stage | Cache mounts | Base image           |
|-----------------------------------------|-------|-------------|--------------|----------------------|
| apps/worldview-web/Dockerfile           | 85    | yes (3)     | 3 (pnpm store, corepack ×2, .next/cache) | node:20-alpine |
| services/api-gateway/Dockerfile         | 55    | yes (2)     | 1 (uv)       | python:3.11-slim     |
| services/market-data/Dockerfile         | 60    | yes (2)     | 1 (uv)       | python:3.11-slim     |
| services/content-store/Dockerfile       | 60    | yes (2)     | 1 (uv)       | python:3.11-slim     |
| services/market-ingestion/Dockerfile    | 60    | yes (2)     | 1 (uv)       | python:3.11-slim     |
| services/content-ingestion/Dockerfile   | 60    | yes (2)     | 1 (uv)       | python:3.11-slim     |
| services/knowledge-graph/Dockerfile     | 66    | yes (2)     | 1 (uv)       | python:3.11-slim     |
| services/alert/Dockerfile               | 54    | yes (2)     | 1 (uv)       | python:3.11-slim     |
| services/rag-chat/Dockerfile            | 71    | yes (2)     | 1 (uv)       | python:3.11-slim     |
| services/nlp-pipeline/Dockerfile        | 70    | yes (2)     | 1 (uv)       | python:3.11-slim     |
| services/portfolio/Dockerfile           | 67    | yes (2)     | 1 (uv)       | python:3.11-slim     |
| services/intelligence-migrations/Dockerfile | 22 | **no**      | **0**        | python:3.12-slim     |

The Python services are nearly identical clones — high leverage for a shared base.

`.dockerignore` is whitelist-style at repo root and correctly minimizes context.
Good (avoids sending the 36 MB `src/` Claude Code reference copy and the 1 GB
`apps/worldview-web/.next` to the daemon).

---

## 3. Per-Dockerfile Findings

### 3.1 `apps/worldview-web/Dockerfile` (the slowest of the three)

What's **already good**:
- 3-stage build (deps / builder / runner) — runner is a clean `node:20-alpine`.
- pnpm content-addressable store mounted via `--mount=type=cache,target=/root/.local/share/pnpm/store`.
- Corepack binary cache mount.
- Next.js incremental `.next/cache` mount.
- Lockfile + workspace config copied **before** source — install layer is
  correctly invalidated only on lock changes.
- `output: standalone` produces a tiny runtime image (~120 MB).

What still hurts:
1. **`--no-cache` defeats every cache mount layer-reuse semantics.** With
   `--no-cache`, every RUN is re-executed; the BuildKit cache mounts still help
   (pnpm store + .next/cache survive), but the install step still walks 1500
   packages to validate the lockfile. This is the biggest single source of the
   ~9-11 min cold time.
2. **`pnpm install --filter worldview-web`** without `--prod=false`/`--prod`
   handling means devDependencies (~600 MB) are installed and then carried
   forward to the builder. The standalone output strips them at `next build`
   time, but the intermediate stage is heavy.
3. **No `--cache-from`** for cross-machine / cross-branch reuse. CI and
   different worktrees each warm their own cache.
4. **`next build` is single-threaded for the heavy webpack chunks.** Cannot be
   fixed at Dockerfile level but Turbopack (already supported in 15.x) would
   shave 15-30%.

Ranked recommendations:

| Rank | Change | Expected savings |
|------|--------|------------------|
| 1    | Stop using `--no-cache` in `make dev-rebuild` (use `--pull` instead, or invalidate explicitly via `--build-arg CACHEBUST`) | 4-7 min |
| 2    | Add `--cache-to=type=registry,ref=ghcr.io/.../worldview-web:buildcache --cache-from=...` (or `type=local`) | 2-4 min on cold |
| 3    | Split `next build` into a separate stage that only copies `apps/worldview-web/{src,public,next.config.ts,tsconfig.json}` (not the whole app dir) so editing `tests/` doesn't invalidate the build | 15-30 s per code-only build |
| 4    | Add `NEXT_TURBOPACK=1` (eval first) or `pnpm next build --turbo` | 15-30 % on `next build` |
| 5    | Use `pnpm fetch` + `pnpm install --offline` instead of `pnpm install --frozen-lockfile`; `fetch` is purely network-bound and benefits more from the store mount | 10-20 s warm |

### 3.2 `services/api-gateway/Dockerfile` and `services/market-data/Dockerfile`

These two are structurally identical (and identical to 8 other Python services).

What's **already good**:
- Multi-stage with thin runtime.
- `uv` (not pip) for resolution — already 10-50× faster than pip.
- `--mount=type=cache,target=/root/.cache/uv` — wheel cache survives `--no-cache`.
- `python:3.11-slim` is reasonable (~45 MB compressed).
- Only `pyproject.toml` + `src/` are copied (no tests, no `.venv`).

What hurts:
1. **No separation between dep-resolution copy and source copy.** Both
   `pyproject.toml` AND `src/` are copied before the install step. This means
   any code change in any lib's `src/` invalidates the install layer (~30-60 s
   on a warm build). The install step depends on `pyproject.toml` only, not
   source, but `uv pip install /build/libs/common` *does* install from source
   so it actually does need the src. Still — split it: install with
   `pyproject.toml` + a stub `src/__init__.py`, then copy real `src/` afterward
   and reinstall with `--no-deps`.
2. **No shared Python base image.** Every Python service repeats:
   - `pip install uv==0.4.29` (~3 s × 10 services = 30 s wasted)
   - The full slim base layer (45 MB × 10 pulls when cache is cold)
   - The runtime stage `useradd` (~0.5 s × 10)
3. **All 5-7 libs are re-installed source-by-source on every change to any of
   them**, because they all live above the cache barrier. With a single
   `uv pip install -e` over an exploded workspace this is unavoidable; with
   wheels published to a local file index it would cache per-lib.
4. **`pip install uv` itself is ~3-5 s.** Should be baked into a base image.
5. `python:3.11-slim` — the rest of the platform (intelligence-migrations) uses
   `3.12`. Inconsistent and `3.12` images are smaller and faster.

Ranked recommendations:

| Rank | Change | Expected savings |
|------|--------|------------------|
| 1    | Introduce `infra/docker/python-base/Dockerfile` → `worldview-python-base:3.12-slim` that bakes `uv`, system deps, the appuser, and pre-installs `libs/common`, `libs/messaging`, `libs/observability`, `libs/contracts` as wheels. Each service `FROM worldview-python-base AS builder`. | 30-90 s per cold build |
| 2    | Stop using `--no-cache`. The uv cache mount makes it ineffective anyway. | 60-180 s per build |
| 3    | Split copy: `COPY libs/*/pyproject.toml` → install stubs → `COPY libs/*/src/` → re-install. Or migrate the libs to publish wheels in a build-time index. | 15-30 s |
| 4    | Use `uv sync` + a checked-in `uv.lock` instead of `uv pip install` from pyproject. `sync` resolves once and reuses. | 5-15 s |
| 5    | Upgrade to `python:3.12-slim` repo-wide for consistency with intelligence-migrations. | marginal |

### 3.3 `services/intelligence-migrations/Dockerfile`

Single-stage, no cache mount, no multi-stage. Build is only ~30 s so it's not
in the critical path, but it should still adopt the shared base image once that
exists.

---

## 4. Layer-Invalidation Analysis (the API gateway worked example)

Trace for **code change in `services/api-gateway/src/api_gateway/routes/foo.py`**:

1. `FROM python:3.11-slim AS builder` — cached.
2. `RUN pip install uv==0.4.29` — cached.
3. `COPY libs/common/pyproject.toml` ... — cached.
4. `COPY libs/common/src/` — **cached** (common src didn't change).
5. ... through `libs/messaging/src`, `libs/observability/src` — cached.
6. `COPY services/api-gateway/pyproject.toml` — cached.
7. `COPY services/api-gateway/src` — **INVALIDATED** (this is the change).
8. `RUN uv pip install ...` — **re-executes** but `uv` cache mount means
   downloads are skipped; only the local `api-gateway` package is reinstalled.
   Should take 5-15 s.
9. Runtime stage `COPY --from=builder` layers all invalidate.

**Conclusion**: With a warm BuildKit cache and **without `--no-cache`**, a code
change in `api-gateway` should rebuild in ~15-25 s. The 6-minute number per
service comes entirely from `--no-cache`.

---

## 5. Platform-Level Recommendations (ranked by impact)

1. **Stop using `--no-cache` as the default `make dev-rebuild` recipe.**
   `infra/Makefile` line `$(COMPOSE_DEV) build --no-cache` should become
   `$(COMPOSE_DEV) build --pull` (or split into `dev-rebuild` and
   `dev-rebuild-clean`). This single change collapses 18 min → 2 min. Add a
   `make dev-rebuild-clean` for the rare full reset.

2. **Build in parallel.** `docker compose build` is serial by default. Add
   `--parallel` flag (Compose v2 supports it). Saves 30-50 % of wall time when
   building >1 service.

3. **Shared `worldview-python-base` image.** Build once, push to a local
   registry (or just tag locally). Bakes `uv`, system deps, the appuser, and
   pre-installs the four "common" libs (`common`, `contracts`, `messaging`,
   `observability`). All 10 Python service Dockerfiles drop from ~60 lines to
   ~25 and skip ~30-90 s of cold build.

4. **Registry-backed build cache (`--cache-to=type=registry`).** Especially
   valuable for CI and for working across git worktrees. The pnpm and uv
   mounts are local-only; a registry cache shares across machines.

5. **Detect change scope and skip irrelevant rebuilds.** Add
   `scripts/dev-rebuild-changed.sh` that does `git diff --name-only main...HEAD`
   and only rebuilds services whose `src/` or `pyproject.toml` changed. For a
   backend-only PR, the 9-minute frontend build is pure waste.

---

## 6. Reference: Optimal Dockerfile Patterns

### 6.1 Canonical pnpm-cached Next.js Dockerfile

The existing `apps/worldview-web/Dockerfile` is already close to the canonical
pattern. Improvements (annotated diff style):

```dockerfile
# syntax=docker/dockerfile:1.7
FROM node:20-alpine AS deps
WORKDIR /workspace
RUN --mount=type=cache,target=/root/.local/share/corepack \
    corepack enable && corepack prepare pnpm@10 --activate

# Lockfile + workspace metadata only — never source.
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/worldview-web/package.json ./apps/worldview-web/

# `pnpm fetch` populates the store from lockfile only; later `--offline` install
# is purely local-disk and survives --no-cache because the store is mounted.
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm fetch
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile --offline --filter worldview-web

# ── builder ─────────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /workspace
COPY --from=deps /workspace/node_modules ./node_modules
COPY --from=deps /workspace/apps/worldview-web/node_modules ./apps/worldview-web/node_modules
COPY pnpm-workspace.yaml pnpm-lock.yaml package.json ./
# Copy only what `next build` needs — splits the layer so editing tests/ or
# storybook/ does not invalidate the cached build.
COPY apps/worldview-web/package.json apps/worldview-web/next.config.ts \
     apps/worldview-web/tsconfig.json apps/worldview-web/postcss.config.mjs \
     apps/worldview-web/tailwind.config.ts ./apps/worldview-web/
COPY apps/worldview-web/src ./apps/worldview-web/src
COPY apps/worldview-web/public ./apps/worldview-web/public

ARG API_GATEWAY_URL=http://api-gateway:8000
ENV API_GATEWAY_URL=${API_GATEWAY_URL} NEXT_TELEMETRY_DISABLED=1

RUN --mount=type=cache,target=/workspace/apps/worldview-web/.next/cache \
    --mount=type=cache,target=/root/.local/share/pnpm/store \
    cd apps/worldview-web && pnpm build

# ── runner (unchanged) ──────────────────────────────────────────────────────
```

### 6.2 Canonical Python service Dockerfile (with shared base)

```dockerfile
# syntax=docker/dockerfile:1.7
ARG BASE=worldview-python-base:3.12-slim
FROM ${BASE} AS builder
WORKDIR /build

# Service-specific lib (not in base) + the service itself.
COPY libs/storage/pyproject.toml /build/libs/storage/pyproject.toml
COPY libs/storage/src /build/libs/storage/src
COPY services/market-data/pyproject.toml /build/services/market-data/pyproject.toml
COPY services/market-data/src /build/services/market-data/src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /opt/.venv \
        /build/libs/storage \
        /build/services/market-data

FROM ${BASE} AS runtime
COPY --from=builder /opt/.venv /opt/.venv
COPY --from=builder /build/services/market-data/src /app/src
COPY services/market-data/alembic /app/alembic
COPY services/market-data/alembic.ini /app/alembic.ini
COPY infra/kafka/schemas /app/infra/kafka/schemas
ENV PATH="/opt/.venv/bin:$PATH" PYTHONPATH="/app/src"
USER appuser
EXPOSE 8003
CMD ["uvicorn", "market_data.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8003"]
```

---

## 7. Action Items (priority order)

| Pri | Action | Owner | Effort |
|-----|--------|-------|--------|
| P0  | Replace `make dev-rebuild` default with non-`--no-cache` build; add `dev-rebuild-clean` for full reset | platform | 5 min |
| P0  | Add `--parallel` to compose build commands | platform | 5 min |
| P1  | Create `infra/docker/python-base/Dockerfile` and migrate 1 service as proof | platform | 2 h |
| P1  | Migrate remaining 9 Python services to shared base | platform | 1 h |
| P2  | Add `--cache-to`/`--cache-from=type=registry` to CI builds | CI | 1 h |
| P2  | `scripts/dev-rebuild-changed.sh` — diff-aware rebuild | platform | 1 h |
| P3  | Split worldview-web builder COPY into granular paths | frontend | 30 min |
| P3  | Evaluate Turbopack for `next build` | frontend | 1 h (eval) |

Cumulative impact: 18 min → **~90 s** for the typical iteration loop and
**~6 min** for the rare fully-clean rebuild.
