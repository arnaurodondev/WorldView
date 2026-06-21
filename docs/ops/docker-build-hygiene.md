# Docker Build Hygiene — Why a Rebuild Ships Stale Code

> **TL;DR** — A service's app, its `*-migrate` job, and every `*-consumer` /
> `*-worker` / `*-scheduler` / `*-dispatcher` are **separate Docker images**.
> `docker compose build <service>` updates **only that one image**. To ship a
> code change to a whole family reliably, use:
>
> ```bash
> make rebuild SVC=market-data        # no-cache, rebuilds + recreates ALL variants
> # or
> scripts/rebuild_service.sh market-data
> ```

---

## The bug class: per-variant images (DEPLOY-STALENESS)

In `infra/compose/docker-compose.yml`, every variant of a service has its **own
`build:` block** pointing at the same Dockerfile/context. Docker Compose
therefore builds and tracks a **separate image per compose service**, named
`worldview-<service-name>:latest`. There is **no shared-image (`image:`)
pattern** — all 72 built services carry their own `build:` block.

Family sizes (number of separate images that must each be rebuilt for one code
change):

| Family              | # compose services (images) |
|---------------------|-----------------------------|
| knowledge-graph     | 15 |
| nlp-pipeline        | 12 |
| market-data         | 9  |
| alert / portfolio   | 6 each |
| content-store       | 5  |
| content-ingestion   | 5  |
| market-ingestion    | 5  |
| rag-chat            | 3  |

### Consequence

`docker compose build market-data` rebuilds **only** `worldview-market-data:latest`.
The migrate job and every consumer keep running their **old** images. So a code
fix appears "not to deploy" until you rebuild every variant. Observed incidents:

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

## Why not just refactor compose to a shared image?

The cleanest structural fix is to give each family **one** `build:` block and
have siblings reference it via `image: worldview-<family>:latest`. That removes
the duplicate-image footgun entirely. It was **not** done here because
`infra/compose/docker-compose.yml` is under heavy concurrent edit by multiple
sessions (healthchecks, kafka instance ids); a sweeping rewrite of 72 build
blocks would collide. The script/Make target is the low-risk, non-compose fix.
If/when the compose file stabilises, migrating each family to a shared `image:`
is the recommended follow-up.

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
