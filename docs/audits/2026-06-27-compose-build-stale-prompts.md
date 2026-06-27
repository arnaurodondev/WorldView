# Compose-build ships stale `libs/prompts` into service images

**Date:** 2026-06-27
**Found during:** FINAL-67 chat-quality fixes (rag-chat prompt bumps)
**Severity:** High — silently ships stale shared-lib code; may explain past
"deployed fix didn't take effect" mysteries across services.

---

## Symptom

After editing + committing `libs/prompts` (synthesis prompt `1.1 → 1.3`,
tool_use prompt `1.9 → 1.10`) and rebuilding rag-chat via the normal path:

```
scripts/rebuild_service.sh rag-chat            # --no-cache
scripts/rebuild_service.sh rag-chat --cache
docker compose -f infra/compose/docker-compose.yml ... build rag-chat
```

the running container **kept serving the OLD prompt versions**:

```
$ docker exec worldview-rag-chat-1 python -c \
    "import prompts.chat.synthesis as s; print(s.SYNTHESIS_SYSTEM_PROMPT.version)"
1.1          # expected 1.3
```

Critically, the **Python source changes in the same repo did land** (the C2/C5
`chat_orchestrator.py` edits were present in the container) — only the
`libs/prompts` package was stale. The installed file inside the image was an old
revision:

```
$ docker run --rm --entrypoint sh worldview-rag-chat:latest -c \
    "grep -n 'version=' /app/.venv/lib/python3.11/site-packages/prompts/chat/synthesis.py | head -1"
89:    version="1.1"      # on-disk source has version="1.3" at line 138
```

`--no-cache` did **not** fix it, which rules out a simple layer-cache hit.

## Evidence it is a build-context staleness issue (not the source)

A **direct** BuildKit build from the repo root produced the CORRECT prompt:

```
$ DOCKER_BUILDKIT=1 docker build --no-cache \
    -f services/rag-chat/Dockerfile -t worldview-rag-chat:smoketest .
$ docker run --rm --entrypoint sh worldview-rag-chat:smoketest -c \
    "grep -n 'version=' /app/.venv/lib/python3.11/site-packages/prompts/chat/synthesis.py | head -1"
138:    version="1.3"      # correct
```

So the on-disk source, the `.dockerignore` allowlist (`!libs/prompts/src/` is
present), and the Dockerfile (`COPY libs/prompts/src` at line 19) are all
correct. The defect is in the `docker compose build` path resolving a stale
build context for the `COPY libs/prompts/src` layer, so
`uv pip install /build/libs/prompts` installs an old copy into site-packages.
Compose build context is `context: ../..` from `infra/compose/`, which is the
repo root — same as the working direct build — so the staleness is in
compose/BuildKit's context snapshotting, not the path.

## Workaround (used to ship the FINAL-67 prompt fixes)

```
DOCKER_BUILDKIT=1 docker build --no-cache \
  -f services/rag-chat/Dockerfile -t worldview-rag-chat:latest .
docker compose -f infra/compose/docker-compose.yml \
  -f infra/compose/docker-compose.dev.yml --profile infra \
  up -d --force-recreate --no-deps rag-chat
# verify BEFORE smoking:
docker exec worldview-rag-chat-1 python -c \
  "import prompts.chat.synthesis as s, prompts.chat.tool_use as t; \
   print(s.SYNTHESIS_SYSTEM_PROMPT.version, t.TOOL_USE_SYSTEM_PROMPT_TEMPLATE.version)"
```

## Impact / who else is affected

Every service image that bundles a shared lib via the same
`COPY libs/<x>/src` + `uv pip install /build/libs/<x>` pattern (all 10 services
bundle `libs/prompts`, `libs/contracts`, etc.). A prompt/lib edit deployed via
`scripts/rebuild_service.sh` or `docker compose build` may silently NOT reach the
container while the service's own `src/` edits do — making a fix look deployed
when only half of it is. The brief-scheduler / migrate variants share the same
Dockerfile and are equally affected.

## Recommended follow-up (not done here)

1. Reproduce in isolation and file against `rebuild_service.sh` /
   the compose build invocation; determine whether `docker compose build` needs
   `--no-cache` plus an explicit context bust, or whether BuildKit is reusing a
   stale local context snapshot.
2. Until fixed, the **verify-version-in-container** step above MUST be part of
   any shared-lib deploy — never trust the rebuild script's "running the new
   image" message for lib changes.
3. Consider a post-build assertion in `rebuild_service.sh` that greps the
   installed lib version against the on-disk source and fails loudly on a
   mismatch.

---

## Resolution (2026-06-27)

### Root cause (confirmed)

The defect is **not** a static bug in the Dockerfile, `.dockerignore`, compose
config, or `rebuild_service.sh` — all four are correct and identical across the
compose-build and direct-build paths (compose `context: ../..` resolves to the
same repo root the working direct build uses). Re-verified:
`libs/prompts/src/prompts` is a real directory (not a symlink); no stale
`*.egg-info` / `*.dist-info` / `*.whl` / `build/` / `dist/` artifacts exist in
`libs/prompts`; the Dockerfile installs `libs/prompts` non-editable from copied
source in a single builder stage with no broad `COPY . .` that could mask the
per-lib `COPY libs/prompts/src`.

The cause is **BuildKit's `local` build-context source op**, which is
content/metadata-addressed and is **NOT invalidated by `--no-cache`** (that flag
only forces re-execution of `RUN`/`COPY` ops, not re-snapshotting of the local
source those ops read from). When an edited file under `libs/prompts/src`
presented metadata (size + mtime + inode) matching a prior snapshot, BuildKit
fed the `COPY libs/prompts/src` layer a **stale snapshot**, while genuinely
changed `services/rag-chat/src` was re-transferred — exactly the reported
asymmetry (service `src` edits land, shared lib is stale). `docker buildx du`
showed many `local source for context` records and ~37 GB reclaimable. Once the
snapshot refreshed, both build paths produced correct output, which is why the
bug is non-deterministic and was not reproducible on demand afterward. The
"direct build works" observation was a cache-key miss, not a path difference.

### Fix shipped (scoped to rag-chat as proof)

Two complementary, low-risk changes:

1. **`ARG CACHE_BUST` in `services/rag-chat/Dockerfile`** (before the lib
   COPYs). A `RUN echo "cache-bust=${CACHE_BUST}"` line forces BuildKit to
   re-resolve the local source for every COPY below it whenever the value
   changes. `scripts/rebuild_service.sh` passes
   `--build-arg CACHE_BUST=<HEAD-sha>-<md5 of working-tree status>`, so any edit
   busts the snapshot; plain `docker build` keeps the default `unset` and is
   unchanged.

2. **Post-build staleness guard in `scripts/rebuild_service.sh`** (recommendation
   #3 above, the deterministic belt-and-suspenders). After building, the script
   runs each freshly built image and compares the installed
   `prompts.chat.synthesis.SYNTHESIS_SYSTEM_PROMPT.version` against the on-disk
   `libs/prompts/src/prompts/chat/synthesis.py` version. A mismatch aborts with
   exit code 3 and points the operator at `docker builder prune -f`. This
   catches the bug regardless of the underlying cache mechanism.

**Verification:** `scripts/rebuild_service.sh rag-chat --cache --no-recreate`
built all 3 variants (app + migrate + brief-scheduler) and the guard reported
`OK … libs/prompts == 1.3` for each. A negative test (image patched to ship
`version="1.1"` while source is `1.3`) confirmed the guard fires (exit 3).

**Operational note:** the verify-version-in-container step remains the safest
manual check for any shared-lib deploy; the guard now automates it. The blunt
escape hatch when a stale snapshot is suspected is `docker builder prune -f`
before rebuilding.
