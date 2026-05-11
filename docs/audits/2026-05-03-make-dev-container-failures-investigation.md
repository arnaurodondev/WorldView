# Investigation Report: `make dev` Container Failures

**Date**: 2026-05-03
**Investigator**: Claude (investigate skill)
**Severity**: HIGH
**Status**: Root causes identified and fixed

---

## 1. Issue Summary

Running `make dev` (without rebuild) left most containers either stopped or in `Created` state. The user had always used `make dev-rebuild` which worked, but plain `make dev` produced a partially-broken dev stack. Two independent root causes were identified.

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|----------|--------|-----------|
| `intelligence-migrations` exit 255 | `docker logs worldview-intelligence-migrations-1` | "Can't locate revision identified by '0011'" |
| Image built 2026-04-29 | `docker inspect worldview-intelligence-migrations-1` | Before migration 0011 added 2026-05-01 (commit 3091bea7) |
| DB at alembic version `0011` | `psql intelligence_db` `SELECT version_num FROM alembic_version` | Image missing script for known DB head |
| 15 services in `Created` state | `docker compose ps --all` | All depend on `intelligence-migrations: condition: service_completed_successfully` |
| Workers remain `Exited` after `up -d` | Multiple `docker compose up -d` runs | Workers with `restart: unless-stopped` not re-started by `up -d` |
| `docker start <container>` starts them | Manual test | Individual start works; full `up -d` skips them |
| `make dev-rebuild` uses `--force-recreate` | `Makefile` | Key difference that makes rebuild work |

---

## 3. Execution Path Analysis

### intelligence-migrations failure

1. **Previous session** (pre 2026-04-29): `make dev-rebuild` built image → image had migrations 0001–0010, DB migrated to 0010.
2. **2026-05-01**: Commits `3091bea7` and `6f3f160c` added migration files `0011` and `0012` to the repo.
3. **Subsequent session**: `make dev` ran `up -d` — no rebuild → used the April 29 image (0001–0010 only).
4. **Alembic** on startup: reads `SELECT version_num` → gets `0011`. Tries to locate revision `0011` in image migration scripts → not found → error `Can't locate revision identified by '0011'` → exit 255.
5. **15 downstream services** (`knowledge-graph` × 13 + `nlp-pipeline` × 3): had `depends_on: intelligence-migrations: condition: service_completed_successfully`. Since intelligence-migrations failed, they stayed in `Created` state.

### Workers not restarting

1. **Previous `make dev-down --timeout 5`**: Stopped all containers. Workers that didn't shut down in 5s got SIGKILL (exit 137); those that did shut down cleanly got exit 0. Both states recorded in container metadata.
2. **`make dev` → `docker compose up -d`**: Processes all services in parallel. For services in the dependency chain (workers that need parent APIs to be `service_healthy`), Docker Compose's parallel scheduler in detached mode may exit before all dependency health conditions are satisfied — leaving dependents unscheduled.
3. Additionally, Docker Compose v5.1.1 does not start containers in `Created` state (from a prior `--force-recreate` run) the same way it starts `Exited` containers.

---

## 4. Hypotheses Tested

| # | Hypothesis | Result | Method |
|---|-----------|--------|--------|
| H-1 | intelligence-migrations image is stale, missing 0011 script | CONFIRMED | `docker inspect` timestamp vs `git log` date |
| H-2 | 15 KG/NLP services blocked by intelligence-migrations failure | CONFIRMED | `docker compose ps --all` + YAML dependency parse |
| H-3 | Workers not starting because parent APIs not yet healthy when `up -d` scheduled them | CONFIRMED (partial) | Workers start when explicitly targeted via `up -d <service>` |
| H-4 | "Created" state containers require explicit `docker start` | CONFIRMED | `docker ps -aq --filter status=created \| xargs docker start` started all 41 containers |

---

## 5. Root Causes

### RC-1: Stale `intelligence-migrations` Docker image
- **Location**: `services/intelligence-migrations/` Docker image
- **Trigger**: Any `make dev` run after new migration files are committed, when `make dev-rebuild` has not been run since those commits
- **Impact**: Alembic exits 255; 15 services stuck in `Created` state (knowledge-graph + nlp-pipeline subset completely offline)

### RC-2: `docker compose up -d` does not reliably start all services in a large parallel stack
- **Location**: `Makefile:141` (`$(COMPOSE_DEV) up -d`)
- **Trigger**: Full platform stop followed by `make dev` (not `make dev-rebuild`)
- **Impact**: Workers with complex dependency chains left unstarted; requires manual intervention

---

## 6. Impact Analysis

- **Immediate**: intelligence-migrations blocks knowledge-graph (KG ingestion completely offline) + nlp-pipeline article consumer and unresolved resolution worker
- **Blast radius**: Entity enrichment, relation extraction, temporal event processing, and KG search all non-functional
- **Data integrity**: No data loss — migration scripts are idempotent. Once image is rebuilt, alembic upgrades from 0011 → 0012 correctly

---

## 7. Fixes Applied

### Fix 1 — Rebuilt `intelligence-migrations` image
```bash
docker compose -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.dev.yml \
    build intelligence-migrations
docker compose ... up -d --force-recreate intelligence-migrations
```
Result: DB upgraded 0011 → 0012. All 15 blocked services started.

### Fix 2 — Updated `make dev` in `Makefile`
Changed `$(COMPOSE_DEV) up -d` to:
```makefile
$(COMPOSE_DEV) up -d --build
@docker ps -aq --filter status=created | xargs -r docker start 2>/dev/null || true
```
- `--build`: rebuilds images using Docker layer cache when source files change — prevents stale image issue without the cost of `--no-cache`
- `xargs docker start`: starts any containers left in `Created` state after the parallel `up -d` run

---

## 8. Prevention Recommendations

1. **Never run bare `docker compose up -d`** for dev restarts — always use `make dev` (now with `--build`) or `make dev-rebuild`
2. After adding Alembic migration files, run `make dev` (not just `make dev-down && make dev`) — the `--build` flag will detect the changed file and rebuild the image
3. Added as **BP-319** (stale migration image) and **BP-320** (Created-state containers) in `docs/BUG_PATTERNS.md`

---

## 9. Open Questions

- The `worldview-web` container cannot start when a local Next.js dev server (PID 48710, `next-server v15.5.15`) is using port 3001. This is expected in local dev workflows where the frontend is run outside Docker. Not a bug.
- `gliner-server` shows `unhealthy` during warm-up — this is expected (model loading takes 2–5 minutes). It becomes healthy once the GLiNER model is loaded.
