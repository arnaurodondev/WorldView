# Consolidated Remediation Plan — 5 Open Items (2026-06-22)

Synthesis of five root-cause investigations. **Items 3/4/5 are DONE this session;
items 1/2 are the "coordination bundle" prepared here for review (NOT applied).**

Per-item detail lives in:
- `2026-06-22-postgres-split-brain-rootcause.md`
- `2026-06-22-memory-cap-policy.md`
- `2026-06-22-alert-consumer-pollloop-wedge-rootcause.md`
- `2026-06-22-promoter-query-rootcause-and-rewrite.md`
- `2026-06-22-ingestion-events-bloat-idle-in-tx-rootcause.md`

---

## Status board

| # | Item | Root cause | Status |
|---|------|-----------|--------|
| 3 | Alert poll-loop wedge | Stale pre-F-006 image + broker starvation | ✅ rebuilt `--no-cache` + redeployed (verifying) |
| 4 | Promoter 2×1.13M/cycle | Per-row correlated density subquery × full relations scan | ✅ CTE rewrite committed — **1.13M→12k (~93×)**, result set proven identical (31==31, gated 609==609) |
| 5 | ~~ingestion_events bloat~~ | **MISDIAGNOSED** — not bloated | ✅ Disproven on verify: real count(*)=1,247,297 rows, 6.3% dead (normal). Agent used a stale `n_live_tup`=19,853 as the count; `reltuples`=1.04M was ~accurate. `ANALYZE` applied (harmless); aggressive autovacuum reverted. No bloat/deadlock. |
| 1 | Postgres split-brain | **Multi-worktree compose collision** + unmerged split | ⏸ coordination bundle (this doc) |
| 2 | No memory budget | Incident-driven caps, 4/80 capped | ⏸ coordination bundle (this doc) |

---

## The coordination bundle (items 1 + 2) — needs your decisions

Both stem from **one systemic root cause**: multiple git worktrees share a single
`name: worldview` Compose project, so any `docker compose up -d` from any worktree
mutates the shared container set — and the DB split lives only on the unmerged
`fix/db-perf-consolidation` branch, so the live stack is a mix of two worktrees'
compose files. Fixing this is a prerequisite for both the split AND the memory caps
landing durably (edits to `infra/compose/docker-compose.yml` on the current branch
don't even affect the running stack today).

### Recommended apply sequence

**Phase A — worktree isolation (do first; prevents recurrence).**
1. Set a per-worktree `COMPOSE_PROJECT_NAME` (e.g. export in each worktree's shell /
   a `.env` per worktree) so sibling sessions can't clobber each other's containers.
   Aligns with R42/BP-590 (one checkout per agent).
2. Document: never run `docker compose up` from a worktree against the shared project.

**Phase B — merge the split to mainline.**
3. Merge `fix/db-perf-consolidation` (the only branch with `postgres-intelligence`,
   the `depends_on` rewiring, and the migrations repoint) into the working branch, OR
   cherry-pick its compose/env changes. Until then the split exists only in a worktree.
4. Replace scattered DB hosts with a tracked `${INTELLIGENCE_PG_HOST}` variable;
   eliminate the lone hardcoded `docker-compose.yml:321` (`intelligence-migrations`
   → `@postgres`, stale since a pre-split commit).
5. Add a fail-fast boot guard: a `SELECT inet_server_addr()` healthcheck / startup
   assertion on KG services so a wrong-instance connection crashes loudly instead of
   silently serving a stale graph.

**Phase C — immediate split-brain remediation (after A+B, or as a stopgap now).**
6. `--force-recreate` `knowledge-graph` + `knowledge-graph-scheduler` **from the main
   worktree** (correct env) so they reconnect to `@postgres-intelligence`; fix the
   md-reliability worktree's `docker.env`; repoint migrations.

**Phase D — memory budget (after the split merge, so postgres-intelligence is real).**
7. Apply the per-service `mem_limit` table from `2026-06-22-memory-cap-policy.md §6`:
   - postgres ×2 → **4 GiB each** (pair postgres-intelligence with `work_mem`→64 MB — the one risky cap)
   - kafka → 3 GiB container + heap `-Xms1G -Xmx2G` (currently 4G heap, uses ~1G)
   - **valkey → 2 GiB + `maxmemory 1536mb` + `maxmemory-policy allkeys-lru`** (fixes the unbounded `noeviction` host-OOM risk — highest-value memory fix)
   - minio 4→6 GiB; gliner 8→5 GiB; ollama 6→5 GiB
   - **512 MiB default cap for the ~60-container consumer tail** (so new consumers are born capped — the key systemic fix)
   - Heavy-set sum ~33 GiB (~71% of 46.72 GiB host); validate worst case ≤ ~39 GiB.

---

## Item 5 — CORRECTED: ingestion_events is NOT bloated

On verification the bloat finding collapsed: `SELECT count(*)` = **1,247,297 rows**,
420 MB total / 208 MB heap, **6.3% dead** (normal). The agent mistook a stale
`pg_stat` `n_live_tup` (19,853) for the real row count; `reltuples`=1.04M was roughly
accurate, and autovacuum correctly had not fired (dead tuples were below the legitimate
0.2×reltuples ≈ 208k threshold for a table this size). **No bloat, no deadlock, no
VACUUM FULL needed.** `ANALYZE` was applied (harmless, refreshed stats); the aggressive
per-table autovacuum was reverted (it would over-vacuum a 1.25M-row table).

The two **idle-in-transaction** pins the agent observed are still real (the fundamentals
consumer's per-message write tx and `schedule_tasks.py:execute` scanning 2,102 policies
in one 47–62s tx) — worth shortening for **latency/lock-horizon** reasons, but they are
NOT causing bloat. The `dedup-row-in-own-transaction` idea was also rejected: the
rollback-on-failure that "leaks" dead tuples is *intentional* — committing the dedup row
separately would break retry idempotency (a failed message would never reprocess).

**Lesson (BP candidate):** `n_live_tup` can be wildly stale on a never-analyzed table —
use `count(*)` for ground truth before declaring bloat.

## Cross-cutting: deploy hygiene (the "committed-but-not-deployed" pattern)

TWO of five items (OHLCV crash, alert wedge) were already-fixed code running on stale
images, compounded by BP-696 stale build cache. Recommend a build step that always
`--no-cache`s on dependency/lib changes, or a post-deploy assertion that the running
image contains the expected fix (the in-container `hasattr`/constant checks used this
session). Worth a BP entry + a `make` target.
