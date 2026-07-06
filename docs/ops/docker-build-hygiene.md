# Docker Build Hygiene — Why a Rebuild Ships Stale Code

> **TL;DR** — Every variant of a service family (the app, its `*-migrate` job,
> and every `*-consumer` / `*-worker` / `*-scheduler` / `*-dispatcher`) now
> **shares ONE image**, `worldview-<family>:latest`. The family's primary
> service carries the single `build:` block (and tags the image); every sibling
> references `image: worldview-<family>:latest` and overrides only
> `command:` / `environment:` / `healthcheck:`. So one `build:` per family
> builds the whole family. To ship a code change reliably:
>
> ```bash
> make rebuild SVC=market-data        # builds the ONE family image + recreates ALL variants
> # or
> scripts/rebuild_service.sh market-data
> ```
>
> **Buildable-image count dropped 77 → 16** (10 app families + 6 standalone
> infra images).

---

## The shared-image model (current)

In `infra/compose/docker-compose.yml`, each service **family** has exactly one
`build:` block — on the primary service, which also tags the image via
`image: worldview-<family>:latest`. Every other variant in the family carries
**only** `image: worldview-<family>:latest` (no `build:`) and overrides just the
per-variant keys (`command`, `environment`, `healthcheck`, `depends_on`).

Compose builds the primary once during its build phase, tags it, and every
sibling starts from that same local image. This dropped the buildable-image
count from **77 → 16** (10 app families + 6 standalone infra images:
`postgres`, `postgres-intelligence`, `intelligence-migrations`, `gliner-server`,
`worldview-web`, `synthetic-monitor`). `make rebuild SVC=<family>` is now **1
build instead of N**.

Family sizes (compose services now sharing ONE image each):

| Family              | # variants | shared image |
|---------------------|------------|--------------|
| knowledge-graph     | 15 | `worldview-knowledge-graph:latest` |
| nlp-pipeline        | 12 | `worldview-nlp-pipeline:latest` |
| market-data         | 9  | `worldview-market-data:latest` |
| portfolio           | 8  | `worldview-portfolio:latest` |
| alert               | 7  | `worldview-alert:latest` |
| content-store       | 5  | `worldview-content-store:latest` |
| content-ingestion   | 5  | `worldview-content-ingestion:latest` |
| market-ingestion    | 5  | `worldview-market-ingestion:latest` |
| rag-chat            | 3  | `worldview-rag-chat:latest` |
| api-gateway         | 2  | `worldview-api-gateway:latest` |

> **Constraint that makes this safe:** within every family all variants share
> identical `profiles: [infra, all]`, so the primary (which owns `build:`) is
> always enabled whenever any sibling is — the family image can never be
> requested without also being built.

---

## Historical bug class: per-variant images (DEPLOY-STALENESS)

> **Superseded by the shared-image model above.** Retained because it explains
> why the model exists and what the failure looked like before the refactor.

Previously every variant of a service had its **own `build:` block** pointing at
the same Dockerfile/context, so Docker Compose built and tracked a **separate
image per compose service** (`worldview-<service-name>:latest`) — 72 of them. A
one-line source edit then required rebuilding **every** variant image or the
change appeared not to deploy.

### Consequence (pre-refactor)

`docker compose build market-data` rebuilt **only** `worldview-market-data:latest`.
The migrate job and every consumer kept running their **old** images. So a code
fix appeared "not to deploy" until you rebuilt every variant. Observed incidents:

1. **`market-ingestion-migrate` — `Can't locate revision 0023`.** A new Alembic
   revision was added; `docker compose build market-ingestion` did **not** update
   the separate `market-ingestion-migrate` image, so the migrate job kept running
   the old revision set. Only rebuilding the `*-migrate` service fixed it.
2. **`market-data-intraday-resampling-consumer` ran the OLD resampler.** The
   `market-data` tag had the fix; the consumer's **separate image** did not.

This is **not** a Docker layer-cache bug. A plain `docker compose build <one
service>` (no `--no-cache`) **does** pick up a changed source file in that
service's image — verified by touching `services/market-data/src/.../config.py`
and confirming the marker landed in `worldview-market-data:latest`. The problem
is purely that **siblings are separate images that were never rebuilt**.

---

## Second failure mode: BuildKit crash on mass parallel builds

Do **not** "fix" this by building a whole family in a single
`docker compose build a b c ... n` call. Building many services (a 15-member
family) in one parallel BuildKit invocation can crash the BuildKit grpc frontend
under memory pressure:

```
target <svc>: failed to solve: frontend grpc server closed unexpectedly
```

When that happens the command may still return, leaving **stale images** — the
same deploy-staleness symptom, now with a non-obvious cause. The host has OOM'd
during mass rebuilds. **Build sequentially**, one service at a time. This is what
`scripts/rebuild_service.sh` does (one `docker compose build <svc>` per variant).

---

## When you need `--no-cache`

For normal source edits, a cached build is correct. `scripts/rebuild_service.sh`
defaults to `--no-cache` anyway for maximum reliability (it is run rarely, per
family, and the safety is worth the extra minutes). Pass `--cache` (or
`CACHE=1` to the Make target) when you are confident the cache is sound and want
speed.

Genuine reasons you still need `--no-cache`:

- A change to a file **not** referenced by any `COPY` line cache key (rare here —
  the Dockerfiles `COPY src` directly, so source edits do invalidate the layer).
- Pulled a new base image / changed a pinned dependency without bumping the
  pin.
- You suspect a poisoned cache after an interrupted build.

---

## The reliable workflow

```bash
# Rebuild + recreate every variant of a family (no-cache by default):
make rebuild SVC=market-data
make rebuild SVC=market-ingestion          # includes the *-migrate job
make rebuild SVC=knowledge-graph CACHE=1   # use layer cache for speed

# Or call the script directly (more flags):
scripts/rebuild_service.sh market-data                 # no-cache build + recreate all 9
scripts/rebuild_service.sh market-data --cache         # use layer cache
scripts/rebuild_service.sh market-data --no-recreate   # build only, don't restart
scripts/rebuild_service.sh market-data --prod          # operate on the prod stack
```

The script resolves the family by prefix (`<family>` or `<family>-*`), builds
each variant **sequentially**, then `docker compose up -d --force-recreate
--no-deps` for all of them so every container runs the new image.

### Verifying a change actually landed in a variant

`docker run --rm <img>` immediately after a build can momentarily resolve a stale
`:latest` tag under the containerd image store. To verify deterministically, pin
to the digest:

```bash
ID=$(docker inspect worldview-market-data-intraday-resampling-consumer:latest --format '{{.Id}}')
docker run --rm --entrypoint cat "worldview-market-data-intraday-resampling-consumer@$ID" \
  /app/src/market_data/.../the_changed_file.py | grep "<your change>"
```

---

## The shared-image refactor (done)

The structural fix — give each family **one** `build:` block and have siblings
reference it via `image: worldview-<family>:latest` — **has now been applied**
(see "The shared-image model" above). It removes the duplicate-image footgun
entirely: 71 sibling `build:` blocks collapsed onto 10 family images, so a
`make rebuild SVC=<family>` builds once and every variant runs the fresh image.

Maintenance notes for anyone editing the compose file:

- A **new variant** of an existing family needs `image: worldview-<family>:latest`
  and **no** `build:` block — just its `command`/`environment`/`healthcheck`.
- A **new family** needs exactly one `build:` block (on its primary) plus an
  `image: worldview-<family>:latest` tag; every other member references that tag.
- Keep all members of a family on the **same `profiles:`** so the `build:`-owning
  primary is always enabled when a sibling is (otherwise the image is never built).

**Related:** `docs/bug-patterns/config-docker.md` (BP entry on per-variant
images), `scripts/rebuild_service.sh`, `Makefile` (`rebuild` target).

## `failed to solve: frontend grpc server closed unexpectedly` — missing dockerfile frontend image (NOT memory)

After a **Docker Desktop restart**, EVERY build (`make rebuild`, `docker compose
build`, even a single-image build, even a fresh `docker buildx` container-driver
builder) can fail instantly with:

```
failed to solve: frontend grpc server closed unexpectedly
```

It looks like a BuildKit/memory crash and tempts a build-cache prune (which can
wedge the daemon further). The real cause: the Dockerfiles start with
`# syntax=docker/dockerfile:1`, so BuildKit must pull the **`docker/dockerfile:1`
frontend image** to parse them — and Docker Desktop's restart cleared the image
cache. When BuildKit can't fetch the frontend image, the frontend grpc server
"closes unexpectedly".

**Fix (instant):**
```
docker pull docker/dockerfile:1
```
then re-run the normal build — all builds succeed. No prune, no memory tuning,
no builder recreation needed.

**Diagnosis tells it apart from real memory pressure:** the failure is immediate
(before any build step runs) and identical for a single tiny image; a genuine
OOM fails mid-step on a large image. The classic builder (`DOCKER_BUILDKIT=0`)
is NOT a workaround here — the whitelist `.dockerignore` excludes the Dockerfile
from the context tarball (BuildKit reads it out-of-band; the classic builder
can't → "Cannot locate specified Dockerfile").

Verified 2026-06-20: 3 BuildKit attempts + a fresh container-driver builder all
crashed with this error until `docker pull docker/dockerfile:1`, after which the
identical build completed in 67s.
