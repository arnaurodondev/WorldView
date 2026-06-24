# Memory-Cap Policy Audit — Platform-Wide Memory Budget

**Date:** 2026-06-22
**Scope:** READ-ONLY investigation. Designs a coherent per-service memory budget for the
local Docker Compose stack. **No edits, restarts, or recreates performed.**
**Host:** macOS Docker Desktop VM — **14 CPU / 46.72 GiB RAM**, **80 running containers**.
**Predecessor:** `docs/audits/2026-06-21-platform-cpu-memory-resweep.md` (this audit
designs the long-term fix for the gaps that resweep flagged).

---

## 1. Executive Summary

Only **4 of 80 containers** carry a memory limit today: `kafka` (6 GiB), `minio` (4 GiB),
`ollama` (6 GiB), `gliner-server` (8 GiB). Every other container — including both Postgres
instances, Valkey, Schema Registry, kafka-ui, the frontend, and the entire ~60-container
consumer/worker fleet — runs **uncapped**.

**Root cause:** there is no *platform memory budget*. Limits were added reactively, one at
a time, only to containers that had already produced an Exit-137 OOM (MinIO F-001 on
2026-06-21) or a GC freeze (Kafka, 2026-06-20). Each fix is well-reasoned in isolation, but
no document ever enumerated all heavy containers and sized them against a host RAM budget.
The result is **three uncapped tail-growth risks** with no backstop:

1. **Valkey** — `maxmemory=0` + `maxmemory-policy noeviction` (live-confirmed). Unbounded
   growth, and when it *does* fill, it returns OOM errors to clients instead of evicting.
2. **postgres-intelligence** — uncapped, `work_mem=128 MB × max_connections=120 ≈ 15 GiB`
   theoretical worst-case for sorts/hashes alone, with no container ceiling.
3. **The long tail** — ~60 small Python consumers at ~70–160 MiB each are individually
   harmless but collectively ~6 GiB with no per-container cap; a single leaking consumer
   can grow unbounded.

Steady-state usage is comfortable (**17.04 GiB total / 46.72 GiB**, ~36%). The risk is
purely **uncapped tail growth during rebuild/backfill waves**, which is exactly the
condition that OOM-killed MinIO.

> **Topology note (important):** the live stack is running the **`db-perf-consolidation`
> worktree** compose, which *splits* `intelligence_db` onto a dedicated
> `postgres-intelligence` container (host port 5433). The **main** `infra/compose/docker-compose.yml`
> still has a *single* `postgres`. The compose edits in §6 are written for the **main**
> compose; the postgres-intelligence row applies only while the split-DB worktree compose
> is the one in use. See §7.

---

## 2. Root-Cause Analysis — Why No Budget Exists

| Evidence | Finding |
|----------|---------|
| `grep mem_limit/deploy.resources` across all 6 compose files | Only 4 services have a `deploy.resources.limits.memory`; all are in `docker-compose.yml`. No `mem_limit:` key used anywhere. |
| Each capped service's comment | MinIO cap cites *"the ONLY stateful infra service with no reservation/limit → deterministic OOM victim (F-001)"*; GLiNER cap cites *"the 4G cap was the exit-137 OOM cause (38h outage)"*; Kafka cap cites the *2026-06-20 GC-freeze RCA*. **Every cap is post-incident.** |
| No platform-budget doc | No file enumerates all heavy containers vs a host RAM target. Caps were never sized as a set — e.g. current limit sum (kafka 6 + minio 4 + ollama 6 + gliner 8 = **24 GiB**) already exceeds 50% of host RAM with 76 services still uncapped. |
| Valkey block (compose L296–308) | No `command:` override, no `maxmemory`, no `--maxmemory-policy`. Defaults to unbounded + `noeviction`. Never touched by any incident. |
| postgres-intelligence block (worktree L115–144) | Comment literally says *"Adjust mem_limit/cpus per host"* — i.e. the author knew a cap was needed and left a TODO. |

**Systemic gap:** caps are *incident-driven*, not *policy-driven*. The platform needs a
single budget table (this document) plus a **default cap for the long tail**, so a new
consumer is born capped instead of uncapped.

---

## 3. Current State — Heavy Containers (live `docker stats` + `docker inspect`)

`MemLimit=0` means uncapped (limit shows as the full 46.72 GiB host in `stats`).

| Container | Current usage | % of limit | Current limit | Heap/eviction today |
|-----------|--------------:|-----------:|--------------:|---------------------|
| postgres (OLTP) | 2.262 GiB | — | **none** | shared_buffers=256 MB, work_mem=4 MB, max_conn=500, 78 active |
| postgres-intelligence (OLAP) | 1.473 GiB | — | **none** | shared_buffers=2 GB, work_mem=**128 MB**, max_conn=120, 54 active |
| kafka | 0.95 GiB | 16% | **6 GiB** | `-Xms4G -Xmx4G`, G1GC |
| valkey | 0.093 GiB | — | **none** | `maxmemory=0`, **noeviction** |
| minio | 3.105 GiB | **77%** | **4 GiB** | n/a (page cache/IO buffers) |
| ollama | 0.016 GiB idle | <1% | **6 GiB** | model RSS grows to ~1.7 G (qwen3:0.6b+bge) / +4 G for qwen2.5:7b DEEP |
| gliner-server | 2.136 GiB | 27% | **8 GiB** | DeBERTa-large + batch tensors |
| schema-registry | 0.388 GiB | — | **none** | JVM, default heap |
| kafka-ui | 0.440 GiB | — | **none** | JVM, default heap |
| worldview-web | 0.105 GiB | — | **none** | Next.js node server |
| prometheus | 0.144 GiB | — | **none** | TSDB |
| grafana / loki / tempo / alloy | ~0.05–0.10 GiB each | — | **none** | observability stack |
| **~60 Python consumers/workers** | ~70–160 MiB each (**≈6 GiB total**) | — | **none** | uvicorn/asyncio |

**Live totals:** 17.04 GiB used across all 80 containers (~36% of host).
**Current capped-set limit sum:** 6 + 4 + 6 + 8 = **24 GiB** (51% of host) — already
imbalanced (heaviest-hitters over-provisioned while everything else is uncapped).

---

## 4. Proposed Memory-Budget Table (DESIGN — do not apply blindly)

Target: **sum of all caps ≤ ~70% of 46.72 GiB ≈ 32.7 GiB**, leaving ~14 GiB host headroom
for the VM, Docker daemon, and burst.

| Container | Current use | Current limit | **Proposed limit** | Heap / eviction setting | Rationale |
|-----------|------------:|--------------:|-------------------:|-------------------------|-----------|
| postgres (OLTP) | 2.26 G | none | **4 GiB** | (keep work_mem=4 MB, shared_buffers=256 MB) | OLTP work_mem is tiny; 4 G covers shared_buffers + 500 conns × small sorts + page cache. Sanity: 4 MB × 500 = 2 GB sort worst-case, fits. |
| postgres-intelligence (OLAP) | 1.47 G | none | **4 GiB** | **lower work_mem 128 → 64 MB** | ⚠️ 128 MB × 120 conns = 15 GB sort worst-case **exceeds any sane cap**. With a 4 GiB cap + 2 GB shared_buffers, only ~2 GB remains for sorts → ~15 concurrent heavy sorts before pressure. Drop work_mem to 64 MB (64 × 120 = 7.5 G worst-case; realistically few conns sort at once). **See §5 flag.** |
| kafka | 0.95 G | 6 G | **3 GiB** | `-Xms1G -Xmx2G` | Live heap use ~290 MB–950 MB; 4 G heap is ~4–13× over-provisioned. 2 G heap + ~1 G off-heap/page = 3 G container. G1GC low-pause retained (the GC-freeze fix was heap *headroom*, not 4 G specifically). |
| valkey | 0.09 G | none | **2 GiB** | **`--maxmemory 1536mb --maxmemory-policy allkeys-lru`** | Cache, not a DB of record. Cap container 2 G, maxmemory ~75% (1536 MB), LRU eviction replaces `noeviction`. Fixes the unbounded + OOM-to-client bug. |
| minio | 3.11 G | 4 G | **6 GiB** | n/a | Live 77% of 4 G during rebuild waves — cap is too tight and risks the OOM it was meant to prevent. 6 G gives IO-buffer headroom. |
| ollama | 0.02 G idle | 6 G | **5 GiB** | (model-dependent) | Pulled models ~1.7 G; +4 G only if qwen2.5:7b DEEP is loaded → 5 G covers DEEP + KV cache. Down from 6 G to reclaim 1 G. |
| gliner-server | 2.14 G | 8 G | **5 GiB** | (4 threads pinned) | Live 2.14 G; 8 G was set after the 4 G OOM but is now over-provisioned. Model ~2.6–4 G + batch tensors → 5 G is ample headroom over observed 2.14 G. |
| schema-registry | 0.39 G | none | **1 GiB** | (JVM default ok) | Small JVM; 1 G caps drift. |
| kafka-ui | 0.44 G | none | **1 GiB** | (JVM default ok) | Dev tool; 1 G cap. |
| worldview-web | 0.11 G | none | **1 GiB** | n/a | Next.js prod server; 1 G generous. |
| prometheus | 0.14 G | none | **1 GiB** | n/a | TSDB grows with retention; 1 G cap. |
| **default for all other ~64 containers** | ~70–160 MiB | none | **512 MiB each** | n/a | Long-tail Python consumers/workers/schedulers + grafana/loki/tempo/alloy/vault/etc. A modest cap kills the "one leaking consumer eats the host" class. |

### Host-headroom sum check

| Group | Cap |
|-------|----:|
| postgres ×2 | 8 GiB |
| kafka | 3 GiB |
| valkey | 2 GiB |
| minio | 6 GiB |
| ollama | 5 GiB |
| gliner | 5 GiB |
| schema-registry + kafka-ui + worldview-web + prometheus | 4 GiB |
| ~64 tail containers × 512 MiB | ~32 GiB *nominal* |

The naive sum (≈65 GiB) **exceeds host RAM** — but that is the *nominal* limit ceiling, not
expected use. Docker limits are **ceilings, not reservations**: actual tail use is ~6 GiB,
not 32 GiB. The meaningful budget is the **heavy set** (postgres ×2 + kafka + valkey + minio
+ ollama + gliner + 4 JVM/web/tsdb) = **33 GiB ≈ 71% of host**, which hits the ≤70% target.
The 512 MiB tail cap is a *safety ceiling* per container, deliberately well above the ~160
MiB observed so it never throttles legitimate work; the host is protected by the fact that
all 64 cannot simultaneously approach their ceiling (steady tail ≈ 6 GiB).

**Result:** heavy-set caps 33 GiB + observed tail 6 GiB = **39 GiB worst-realistic / 46.72
GiB (83%)**, with each individual container now backstopped. Steady state stays ~17 GiB.

---

## 5. Risk Flags — Caps That Could OOM Legitimate Work

- ⚠️ **postgres-intelligence (4 GiB cap + work_mem):** this is the only genuinely risky cap.
  At `work_mem=128 MB`, a handful of concurrent AGE/FTS sorts (the OLAP workload this
  instance exists for) can each grab 128 MB+; with `shared_buffers=2 GB` already inside a
  4 GiB cap, only ~2 GiB is left for the connection working set. Heavy KG path/FTS queries
  could hit the cap and trigger the OOM-killer on a *legitimate* query. **Mitigation (part
  of the design):** lower `work_mem` to 64 MB *and* either raise the cap to 5–6 GiB or
  reduce `max_connections` from 120 toward the observed 54. Validate against the heaviest KG
  path-insight query before committing the cap.
- ⚠️ **minio at 4→6 GiB:** the *current* 4 G is the risky one (live 77%). Raising to 6 G is
  the safe direction; flagged only so the recreate isn't deferred.
- ✅ kafka 4 G→2 G heap, gliner 8→5 G, ollama 6→5 G: all sit far above observed RSS; low risk.
- ✅ 512 MiB tail default: 3× the observed ceiling of the largest tail consumer (~160 MiB);
  low risk, but watch the 3 highest (`content-store-consumer` 159 M, `market-ingestion-worker`
  160 M, `nlp-pipeline-article-consumer` 154 M) — if any legitimately spikes past 512 M under
  load, exempt it with an explicit higher cap.

---

## 6. Exact Compose / Env Edits (proposed — NOT applied)

All edits target `infra/compose/docker-compose.yml` unless noted. Compose Swarm-style
`deploy.resources.limits` is already honored by `docker compose up` on this host (the 4
existing caps prove it), so reuse that key for consistency.

### 6.1 Valkey — add command override + cap (fixes noeviction)

```yaml
  valkey:
    image: valkey/valkey:7.2-alpine
    profiles: [infra, all]
    # Cache, not a store of record: bound memory and EVICT (LRU) instead of the
    # default noeviction (which returns OOM errors to clients once full).
    command:
      - "valkey-server"
      - "--maxmemory"
      - "1536mb"
      - "--maxmemory-policy"
      - "allkeys-lru"
    deploy:
      resources:
        limits:
          memory: 2G
    ports:
      - "127.0.0.1:6379:6379"
    volumes:
      - valkey_data:/data
    # ... healthcheck unchanged
```

### 6.2 Kafka — right-size heap + container

```yaml
      # was: -Xms4G -Xmx4G (live use ~290 MB–950 MB; 4G is ~4–13x over-provisioned).
      # GC-freeze fix needed headroom over default 1G, not 4G; 2G keeps low-pause G1GC.
      KAFKA_HEAP_OPTS: "-Xms1G -Xmx2G"
    # ...
    deploy:
      resources:
        reservations:
          cpus: "2.0"
          memory: 2G        # was 5G
        limits:
          memory: 3G        # was 6G
```

### 6.3 MinIO — 4G → 6G

```yaml
    deploy:
      resources:
        reservations:
          memory: 1G
        limits:
          memory: 6G        # was 4G — live 77% of 4G during rebuild waves
```

### 6.4 Ollama 6G → 5G, GLiNER 8G → 5G

```yaml
  # ollama
    deploy:
      resources:
        limits:
          cpus: "4.0"
          memory: 5G        # was 6G

  # gliner-server
    deploy:
      resources:
        limits:
          cpus: "4.0"
          memory: 5G        # was 8G (live 2.14G; 8G post-OOM over-correction)
```

### 6.5 OLTP Postgres — add cap (no work_mem change)

```yaml
  postgres:
    # ... command unchanged: max_connections=500, shared_buffers=256MB, work_mem=4MB
    deploy:
      resources:
        reservations:
          cpus: "1.0"
          memory: 1G
        limits:
          memory: 4G        # NEW backstop
```

### 6.6 postgres-intelligence — add cap + lower work_mem (worktree compose; see §7)

```yaml
  postgres-intelligence:
    command:
      - "postgres"
      - "-c"
      - "shared_buffers=2GB"
      - "-c"
      - "work_mem=64MB"          # was 128MB — 128×120conn = 15GB worst-case sort
      - "-c"
      - "max_connections=120"
    deploy:
      resources:
        limits:
          memory: 4G             # ⚠️ validate vs heaviest KG path/FTS query first (§5)
```

### 6.7 JVM/web/tsdb caps (schema-registry, kafka-ui, worldview-web, prometheus)

Add to each service block:

```yaml
    deploy:
      resources:
        limits:
          memory: 1G
```

### 6.8 Long-tail default (512 MiB)

Compose has no "default per-service limit" primitive. Two safe options:

- **Option A (explicit, preferred for auditability):** add the `deploy.resources.limits.memory: 512M`
  block to each remaining consumer/worker/scheduler service. Verbose but explicit.
- **Option B (YAML anchor):** define an anchor once and merge it into each service:

  ```yaml
  x-tail-mem: &tail-mem
    resources:
      limits:
        memory: 512M
  # then in each small service:
    deploy: *tail-mem
  ```

  Note: an existing `deploy:` block (e.g. with `replicas`) must be merged, not overwritten —
  YAML merge keys don't deep-merge, so services that already set `deploy` need the limit
  inlined.

---

## 7. How to Apply Safely

1. **`mem_limit`/`deploy.resources` changes require a container *recreate*, not a restart.**
   `docker compose restart <svc>` does **not** pick up new resource limits; you must
   `docker compose up -d <svc>` (which recreates) or `--force-recreate`.
2. **Profile-gated services need `--profile all` (compose-recreate gotcha, in memory).**
   Every service here is gated `profiles: [infra, all]` (or similar). A recreate without the
   right `--profile` silently **no-ops** — the container keeps its old limit and you think it
   applied. Use:
   ```
   docker compose -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.dev.yml \
     --profile all up -d valkey kafka minio ollama gliner-server postgres
   ```
3. **Valkey/Kafka/Postgres recreate = brief downtime** for everything depending on them.
   Apply during a quiet window; the dependent consumers will reconnect.
4. **Decide the topology first (§1 note).** The live stack uses the `db-perf-consolidation`
   worktree compose (split postgres-intelligence). Apply §6.6 only there. If/when the split
   is merged to `main`, port the cap into `infra/compose/docker-compose.yml`. Applying the
   main compose's single-`postgres` definition over the running split stack would orphan
   `postgres-intelligence` (and intelligence_db).
5. **Validate postgres-intelligence cap before committing (§5):** run the heaviest KG
   path-insight / FTS query against the 4 GiB-capped container with `work_mem=64MB` and watch
   for OOM-kill (Exit 137) before rolling it into the compose file.
6. **Order:** apply the low-risk caps first (kafka, ollama, gliner, JVM/web, minio↑, tail
   default), confirm a steady stack, then apply the two stateful/risky ones (valkey eviction,
   postgres-intelligence) last with monitoring.

---

## 8. Quick Wins (lowest risk, highest value)

1. **Valkey eviction fix** (§6.1) — closes the unbounded + OOM-to-client hole; cache data is
   disposable so LRU eviction is safe.
2. **MinIO 4→6 GiB** (§6.3) — relieves the live 77% pressure that risks re-OOM.
3. **512 MiB tail default** (§6.8) — single highest-leverage *systemic* fix; turns "uncapped
   by default" into "capped by default" for ~64 containers.
