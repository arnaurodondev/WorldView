# Postgres Split-Brain — Root Cause Analysis — 2026-06-22

**Scope:** READ-ONLY investigation (`docker inspect` / `docker exec` / `git log` / `git blame` /
read compose + env + Makefile). No edits, commits, restarts, or `docker compose` mutations.
**Follows up:** `docs/audits/2026-06-21-postgres-split-optimization.md` (which first detected the
split-brain). That audit said the two KG containers "were never recreated after the repoint." This
audit shows the opposite is true — **they WERE recreated, but from the wrong worktree** — and
identifies the systemic root cause.

---

## TL;DR — the exact mechanism

The Postgres split (`worldview-postgres-1` = OLTP, `worldview-postgres-intelligence-1` =
KG/intelligence) is half-deployed because **multiple git worktrees share one Docker Compose project
(`name: worldview`) while each carries its own, divergent copy of the split configuration.** The
split was authored on one worktree's branch but the running containers were last created/recreated
from *three different worktrees*, two of which predate (or never received) the repoint:

| Container | Live DB host | Created from worktree | Why it is (mis)pointed |
|---|---|---|---|
| `knowledge-graph-1` (KG API) | `@postgres` ❌ | `worldview-wt-md-reliability` | that worktree's `docker.env` still has the OLD `@postgres` value |
| `knowledge-graph-scheduler-1` | `@postgres` ❌ | `worldview-wt-md-reliability` | same — stale `docker.env` in that worktree |
| 13 other KG consumers + `dispatcher` | `@postgres-intelligence` ✅ | `worldview` (main) | main worktree `docker.env` is repointed |
| `postgres-intelligence-1` | n/a (is the DB) | `.claude/worktrees/db-perf-consolidation` | the ONLY worktree whose committed compose defines the split |
| `intelligence-migrations-1` | `@postgres` ❌ | `worldview` (main) + eval.yml | hardcoded in compose since 2026-03-26, pre-split |

Because all worktrees set `name: worldview`, every `docker compose up -d` from *any* of them
targets the **same container namespace** — so the "live" config is simply whichever worktree last
ran `up`/`force-recreate` for that service. There is no single source of truth.

---

## Evidence

### 1. The two mis-pointed KG containers run stale `@postgres`

```
$ docker inspect worldview-knowledge-graph-1 --format '{{.Config.Env}}' | grep DATABASE_URL
KNOWLEDGE_GRAPH_DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/intelligence_db   ❌
KNOWLEDGE_GRAPH_DATABASE_URL_READ=

$ docker inspect worldview-knowledge-graph-scheduler-1 ...
KNOWLEDGE_GRAPH_DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/intelligence_db   ❌
```

A correctly-pointed sibling for comparison:

```
$ docker inspect worldview-knowledge-graph-enriched-consumer-1 ...
KNOWLEDGE_GRAPH_DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres-intelligence:5432/intelligence_db   ✅
```

All KG services use the **identical** compose definition — `env_file:
../../services/knowledge-graph/configs/docker.env`, with **no `environment:` override**
(`docker-compose.yml:1729, 1773, 1799`). So the difference cannot come from the compose file. It
comes from *which `docker.env` was on disk in the worktree that created the container*.

### 2. They were NOT "never recreated" — they were recreated MORE recently, from the wrong worktree

```
knowledge-graph-1            created 2026-06-22T04:14:24Z   (mis-pointed)
knowledge-graph-scheduler-1  created 2026-06-22T06:33:42Z   (mis-pointed)
knowledge-graph-enriched-…   created 2026-06-21T22:52:30Z   (correct)
```

The mis-pointed containers are the *newest*. The prior audit's "never recreated" hypothesis is
**refuted**. The real discriminator is the Compose project labels baked at create time:

```
$ docker inspect <c> --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'

knowledge-graph-1            …/worldview-wt-md-reliability/infra/compose   ❌
knowledge-graph-scheduler-1  …/worldview-wt-md-reliability/infra/compose   ❌
knowledge-graph-enriched-…   …/worldview/infra/compose                     ✅
knowledge-graph-dispatcher-1 …/worldview/infra/compose                     ✅
postgres-intelligence-1      …/.claude/worktrees/db-perf-consolidation/…   (authored the split)
intelligence-migrations-1    …/worldview/… + …/docker-compose.eval.yml     (pre-split)
```

The mis-pointed containers' `config_files` label also includes `docker-compose.dev.yml` and points
at the `worldview-wt-md-reliability` checkout — a different worktree than the correct containers.

### 3. The mis-pointed worktree's `docker.env` still has the OLD value

```
$ grep KNOWLEDGE_GRAPH_DATABASE_URL \
    /Users/arnaurodon/.../worldview-wt-md-reliability/services/knowledge-graph/configs/docker.env
KNOWLEDGE_GRAPH_DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/intelligence_db   ❌ OLD

$ grep KNOWLEDGE_GRAPH_DATABASE_URL \
    /Users/arnaurodon/.../worldview/services/knowledge-graph/configs/docker.env
KNOWLEDGE_GRAPH_DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres-intelligence:5432/intelligence_db   ✅ NEW
```

So when a sibling session ran `docker compose up -d knowledge-graph knowledge-graph-scheduler` from
the `worldview-wt-md-reliability` worktree (e.g. while doing market-data reliability work), Compose
— sharing project `worldview` — recreated those two shared containers using *that worktree's* stale
`docker.env`, silently clobbering the correct config the main worktree had applied. The scheduler at
06:33 is the most recent clobber.

### 4. `docker.env` is gitignored — so the repoint does NOT propagate across worktrees

```
$ git check-ignore services/knowledge-graph/configs/docker.env
services/knowledge-graph/configs/docker.env        # IGNORED
$ git ls-files --error-unmatch services/knowledge-graph/configs/docker.env
(nothing)                                          # NOT tracked
```

`docker.env` is generated locally per-worktree by `scripts/setup-dev.sh` (from the private
`worldview-gitops` repo) — see `make dev-clean` ("re-run setup-dev.sh … to restore"). Because it is
**not version-controlled**, the `@postgres → @postgres-intelligence` repoint applied in the main
worktree never reached the `md-reliability` worktree. Each worktree's env drifts independently. This
is the systemic root cause: **DB host is configured in a per-worktree, untracked file, with no
mechanism to keep worktrees in sync.**

### 5. The split itself lives on only ONE branch (not the current one)

```
$ grep -c 'postgres-intelligence' infra/compose/docker-compose.yml        # current branch
0
$ grep -n 'postgres-intelligence:' .claude/worktrees/db-perf-consolidation/infra/compose/docker-compose.yml
115:  postgres-intelligence:        # service definition
338:      postgres-intelligence:    # intelligence-migrations depends_on
341:      INTELLIGENCE_DB_URL: "postgresql://postgres:postgres@postgres-intelligence:5432/intelligence_db"   ✅ migrations fixed HERE
```

The `postgres-intelligence` service, the migrations repoint, and the `depends_on` rewiring are all
**committed only on `fix/db-perf-consolidation`** (worktree `.claude/worktrees/db-perf-consolidation`).
The currently checked-out branch (`feat/frontend-enhancement-sprint`) has **none of it** — its
compose still hardcodes the migrations URL to the OLD box (see §6) and has no second Postgres. The
live `postgres-intelligence-1` container exists only because that one worktree ran `up` for it.

### 6. `intelligence-migrations` is hardcoded to the OLD box on the current branch

```
$ git blame -L 321,321 infra/compose/docker-compose.yml
5d8b461253 (Arnau Rodon 2026-03-26) 321:  INTELLIGENCE_DB_URL: "postgresql://postgres:postgres@postgres:5432/intelligence_db"
```

Line 321 dates to **2026-03-26 — months before the split.** It was correct then (single Postgres);
it became stale when the split was introduced. The migrations service also declares
`depends_on: postgres` (not `postgres-intelligence`). Live container confirms:

```
$ docker inspect worldview-intelligence-migrations-1 ... | grep INTELLIGENCE_DB_URL
INTELLIGENCE_DB_URL=postgresql://postgres:postgres@postgres:5432/intelligence_db   ❌
# created 2026-06-17 from main worktree — predates the split entirely
```

**Consequence:** any intelligence_db DDL run from the current branch lands on the OLD box, widening
the divergence. The fix exists on `db-perf-consolidation` (line 341) but has not been merged.

### 7. All hardcoded DB-URL sites in compose (full inventory)

```
$ grep -nE '@postgres:5432|@postgres-intelligence:5432' infra/compose/docker-compose.yml
321:  INTELLIGENCE_DB_URL: "postgresql://postgres:postgres@postgres:5432/intelligence_db"            ❌ stale (intelligence-migrations)
784:  DATA_SOURCE_NAME:  "postgresql://…@postgres:5432/postgres?sslmode=disable"                      ✅ postgres_exporter (OLTP box — correct)
```
Plus, in `docker-compose.dev.yml`:
```
PGWEB_DATABASE_URL: postgres://postgres:postgres@postgres:5432/postgres?sslmode=disable             (pgweb — OLTP-only browser; intelligence box not browsable)
```

Only **one** functional hardcode is wrong (line 321). Every application service uses
`env_file: …/docker.env`; the only `environment:`-block DB URL in the whole file is line 321. So the
DB host is sourced from **three scattered places**: (a) per-service untracked `docker.env`, (b) one
hardcoded compose `environment:` value, (c) the implicit `depends_on` graph. No single source of
truth.

---

## Root cause (systemic)

1. **Shared Compose project across worktrees.** `name: worldview` is hardcoded in both
   `docker-compose.yml:28` and `docker-compose.dev.yml:12`. Five+ active worktrees (see
   `git worktree list`) all resolve to the same project, so any `up`/`force-recreate` from any
   worktree silently rewrites the shared containers using *that* worktree's on-disk config. This
   violates the R42/BP-590 intent ("one worktree per agent") because worktree isolation does not
   extend to the Docker layer.

2. **DB host config is untracked and per-worktree.** `docker.env` is gitignored and generated by
   `setup-dev.sh`. The `@postgres-intelligence` repoint was applied only to the main worktree's copy;
   sibling worktrees still carry `@postgres`. Recreating a shared container from a stale worktree
   reintroduces the bug. There is no propagation or validation.

3. **No recreate-on-env-change discipline.** Editing `docker.env` does not change the compose
   config-hash (the file's *content* is read at create time but isn't part of the hash compose
   compares), so a plain `docker compose up -d` may not recreate the container — and when it does, it
   may be from the wrong worktree. The repoint required an explicit `--force-recreate` that was never
   reliably run from the correct worktree for these two services.

4. **Stale pre-split hardcode.** `intelligence-migrations` `INTELLIGENCE_DB_URL` was hardcoded in
   2026-03-26 and never updated when the split landed; the fix exists only on an unmerged branch.

---

## Long-term fix (design — DO NOT APPLY here)

### A. Single source of truth for DB host (eliminate the scatter)
- Introduce a `${INTELLIGENCE_PG_HOST}` / `${OLTP_PG_HOST}` variable, defined once in a tracked
  `infra/compose/.env` (or top of compose via `x-db-hosts`), and reference it everywhere:
  - `docker.env` template (in worldview-gitops `setup-dev.sh`) builds
    `KNOWLEDGE_GRAPH_DATABASE_URL=…@${INTELLIGENCE_PG_HOST}:5432/intelligence_db`.
  - `intelligence-migrations` `environment:` → `INTELLIGENCE_DB_URL: …@${INTELLIGENCE_PG_HOST}:…`
    and `depends_on: postgres-intelligence` (merge the `db-perf-consolidation` change).
- **Eliminate the hardcoded compose URL at line 321** — replace with the variable. `postgres_exporter`
  (784) and `pgweb` should each get role-correct hosts; ideally add an intelligence-box exporter +
  pgweb URL so the new box is observable/browsable.
- Commit the split (`postgres-intelligence` service, repoints, `depends_on`) onto the mainline so it
  is no longer trapped on `fix/db-perf-consolidation`.

### B. Per-worktree Compose project isolation (stop cross-worktree clobbering)
- Replace the hardcoded `name: worldview` with an overridable
  `name: ${COMPOSE_PROJECT_NAME:-worldview}`, and have each worktree export a distinct
  `COMPOSE_PROJECT_NAME` (e.g. derived from the worktree dir) so sibling sessions cannot mutate each
  other's containers. This makes the R42 "one worktree per agent" rule actually hold at the Docker
  layer. (Alternatively: enforce that only the main worktree runs the stack.)

### C. Reliable recreate-on-env-change `make` target
- Add a target that always force-recreates with the correct profile and config files, from the
  current worktree only:
  ```make
  COMPOSE_DEV := docker compose -f infra/compose/docker-compose.yml \
                                -f infra/compose/docker-compose.dev.yml --profile infra
  ## Force-recreate after a docker.env / compose change (picks up new env_file values)
  dev-apply-env:
  	$(COMPOSE_DEV) up -d --force-recreate --no-build
  ```
  Document that **editing any `docker.env` requires `make dev-apply-env`** (a plain `up -d` is not
  guaranteed to recreate on env_file content change). Note the existing memory gotcha
  (`feedback_compose_profile_recreate.md`): profile-gated services no-op on `up -d` without the
  matching `--profile`; the KG services are `profiles:[infra, all]` so `--profile infra` covers them,
  but the target must always pass a profile.

### D. Startup guard against silent split-brain recurrence
- Add a fail-fast assertion in the KG service settings/startup that the configured DB host matches the
  intelligence box, e.g. in `services/knowledge-graph/.../config.py` (pydantic-settings validator) or
  a one-line check in the FastAPI lifespan / scheduler `main`:
  ```python
  # Fail loudly if a KG service is pointed at the OLTP box (split-brain guard).
  expected_host = settings.expected_intelligence_pg_host  # e.g. "postgres-intelligence"
  if expected_host not in str(settings.knowledge_graph_database_url):
      raise RuntimeError(
          f"KG DB URL points at the wrong Postgres instance "
          f"(expected host '{expected_host}'): {settings.knowledge_graph_database_url}"
      )
  ```
  Pair with a compose `healthcheck` that queries `SELECT inet_server_addr()` / current host and
  compares — so a mis-pointed container reports unhealthy instead of silently serving a stale graph.
  This converts the failure mode from "silent diverging reads" to "crash on boot."

### E. Immediate remediation (ops — not applied in this read-only audit)
1. From the **main worldview worktree** (which has the correct `docker.env`), force-recreate the two
   shared containers so they reload the corrected env_file:
   ```
   cd /Users/arnaurodon/.../worldview/infra/compose
   docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile infra \
     up -d --force-recreate --no-build knowledge-graph knowledge-graph-scheduler
   ```
   Verify: `docker inspect worldview-knowledge-graph-1 … | grep DATABASE_URL` shows
   `@postgres-intelligence`.
2. Fix the `md-reliability` worktree's `docker.env` (or stop running the stack from it) so a future
   `up` there cannot re-clobber.
3. Repoint `intelligence-migrations` (compose:321 → `@postgres-intelligence`, `depends_on:
   postgres-intelligence`) — merge the `db-perf-consolidation` change before the next intelligence
   migration.
4. Reconcile the two diverged `intelligence_db` copies (per the 2026-06-21 audit §a), then retire the
   OLD copy on `postgres-1`.

---

## Appendix — commands used (all read-only)

```
docker inspect <c> --format '{{range .Config.Env}}{{println .}}{{end}}'
docker inspect <c> --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'
docker inspect <c> --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}'
docker inspect <c> --format '{{.Created}}'
git worktree list
git blame -L 321,321 infra/compose/docker-compose.yml
git check-ignore services/knowledge-graph/configs/docker.env
grep -nE '@postgres:5432|@postgres-intelligence:5432' infra/compose/docker-compose.yml
```
```
```
