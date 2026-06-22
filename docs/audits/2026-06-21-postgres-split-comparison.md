# Postgres OLTP/OLAP Split — Branch Comparison & Integration Verdict

**Date:** 2026-06-21
**Author:** investigation (read-only)
**Worktree:** `/Users/arnaurodon/Projects/University/final_thesis/worldview-wt-md-reliability`
**Current/unified branch (HEAD):** `feat/md-reliability-followups` @ `7c5425578`
**Candidate branches:**
- `fix/db-perf-consolidation` (tip `2dabab46b`)
- `worktree-postgres-split` (tip `92a88ddc3`)

---

## TL;DR / Verdict

**Use `fix/db-perf-consolidation`. Do a normal merge (or fast-forward of its 3 commits) into `feat/md-reliability-followups`. Do NOT touch `worktree-postgres-split`.**

Two findings dominate:

1. **The actual Postgres-split change is IDENTICAL on both branches.** Both tip commits have the same message, same timestamp (2026-06-21 10:24:43), and touch the same 11 files with byte-identical content (the design doc, gitops diff, init scripts, compose `postgres-intelligence` service, and the KG/NLP/intel-migrations env repointing). The only diff between the two tip commits is line-number context inside `docker-compose.yml`, because the worktree branch's compose file is ~152 lines longer from unrelated work. **Choosing between branches is therefore NOT about the split itself — it is about everything else each branch drags along.**

2. **HEAD is currently in a BROKEN intermediate state that `fix/db-perf-consolidation` repairs.** HEAD already partially absorbed the related perf work (statement_timeout, the `promoted_at` promoter, migration `0061`) but is missing migration `0060` and has a duplicate-`0049` revision collision. `fix/db-perf-consolidation` supplies the missing `0060` (which `0061` chains from) and is the clean completion of this consolidation. `worktree-postgres-split` does NOT contain `0060`/`0061` or the statement_timeout config at all.

`fix/db-perf-consolidation` is a clean, tightly-scoped 3-commit delta on a recent merge-base. `worktree-postgres-split` is a stale, long-lived branch (merge-base 2026-05-20) carrying **1,251 files / +168k lines** of unrelated history (chat-eval harness, CI rescue, observability, PLAN-0104, etc.). Merging it would re-introduce or conflict with a huge amount of work already on HEAD and is effectively un-reviewable.

---

## 1. What each branch actually changes

### `fix/db-perf-consolidation` — 3 commits ahead of HEAD

| Commit | Subject | Scope |
|--------|---------|-------|
| `33e94b699` | perf(kg,nlp): index relation_evidence_raw density (0060) + statement_timeout backstop | migration `0060` (down_rev 0059); KG/NLP `config.py` (`statement_timeout_ms`); `intelligence_db/session.py` + `nlp_db/session.py` apply timeout; unit tests |
| `99b120113` | fix(knowledge-graph): stop promoter re-scanning promoted backlog | migration `0061` (down_rev 0060, adds `promoted_at` + backfill); `relation_evidence_promoter.py` filters `promoted_at IS NULL`; tests; docs |
| `2dabab46b` | **feat(infra): split Postgres into OLTP + dedicated OLAP instance** | the split (see below) |

3-dot diffstat vs HEAD: **24 files, +1021/-59** — but ~half of that (config.py, session.py, 0060/0061, promoter tests) is the perf consolidation, and **much of it already exists on HEAD** (see §3). The net *new* surface area is small and infra-focused.

### `worktree-postgres-split` — 10 commits ahead of HEAD

Only the **tip** commit `92a88ddc3` is the split. The other 9 commits are unrelated long-lived work: PLAN-0104 RAG-Chat campaign, CI rescue, observability B-1 (PLAN-0107), PR #16/#17/#18 merges, a DeepInfraReranker kwarg fix. 3-dot diffstat vs HEAD: **1,251 files, +168,368/-9,681**.

### The split itself (identical on both tips)

- New compose service **`postgres-intelligence`** (`infra/compose/docker-compose.yml`): same image as `postgres` (timescaledb-pg16 + pgvector + Apache AGE), own volume `postgres_intelligence_data`, own init dir, host port `127.0.0.1:5433`, OLAP tuning (`shared_buffers=2GB`, `work_mem=128MB`, `max_connections=120`), healthcheck.
- New init scripts `infra/postgres/init-intelligence/{init-databases.sh,init-test-databases.sh}` create **only** the OLAP databases — `nlp_db` (pgvector), `intelligence_db` (pgvector + pg_trgm + AGE), `kg_db` (AGE).
- Old `infra/postgres/init/init-databases.sh` no longer creates those three DBs (now OLTP-only). Idempotent: existing volumes unaffected.
- Compose repointing: the `intelligence-migrations` job env `INTELLIGENCE_DB_URL` → `postgres-intelligence`; `depends_on` for intel-migrations and nlp-pipeline switched to `postgres-intelligence: service_healthy`.
- Env-example repointing (the runtime config that backs `env_file`): KG `KNOWLEDGE_GRAPH_DATABASE_URL`, NLP `NLP_PIPELINE_DATABASE_URL` + `NLP_PIPELINE_INTELLIGENCE_DATABASE_URL`, prod example, all `postgres` → `postgres-intelligence`.
- Docs: `docs/audits/2026-06-08-postgres-workload-split.md` (design) + `docs/audits/postgres-split-gitops.diff` (the exact env/dev changes for the gitops repo, left for human apply).

**Services that move to OLAP:** knowledge-graph (uses `intelligence_db`, which hosts the live AGE `worldview_graph`), nlp-pipeline (`nlp_db` + reads `intelligence_db`), intelligence-migrations (owns `intelligence_db` DDL). OLTP `postgres` retains portfolio, market-data, gateway, alert, content-store, etc.

---

## 2. How the two branches differ from each other

- **The split content does NOT differ.** Tip-to-tip blob comparison: `init-databases.sh`, KG `docker.env.example`, NLP `docker.env.example` are SAME blobs on both branches. Only `docker-compose.yml` differs, and that diff is purely line-offset noise (the worktree compose carries ~152 extra lines from unrelated services).
- **Neither is a superset of the other for the split** — they are the same split applied to two different bases.
- **`fix/db-perf-consolidation` is the more complete *consolidation*:** it bundles the migration-numbering fix (0060) and statement_timeout, which `worktree-postgres-split` lacks.
- **`worktree-postgres-split` is far more divergent overall** but none of that divergence is the split; it is stale unrelated history rooted at merge-base `9f3cab378` ("Clean main", 2026-05-20), i.e. *before* the PLAN-0089 merge era now on HEAD.

---

## 3. Completeness / correctness signals

**Critical: HEAD is mid-consolidation and currently has a broken Alembic chain.**

- HEAD has **two migrations claiming revision `0049`** with the same `down_revision = "0048"`:
  `0049_age_entity_id_property_index.py` AND `0049_index_relation_evidence_raw_density.py`. This is an Alembic branch/duplicate-revision collision.
- HEAD has migration **`0061`** with `down_revision = "0060"`, **but HEAD has NO `0060`** → `alembic upgrade head` on `intelligence_db` will fail with a missing-revision (KeyError) error.
- `fix/db-perf-consolidation` supplies the missing **`0060`** (`down_revision = "0059"`), the proper parent of `0061`, repairing the chain. (The duplicate-`0049` issue should be confirmed resolved during integration — see Risk.)
- HEAD already has: `statement_timeout_ms` in KG config, the `promoted_at` promoter logic (`relation_evidence_promoter.py`, 12 `promoted_at` refs — identical to the fix branch), and migration `0061`. So the perf commits on `fix/db-perf-consolidation` are largely a **renumbered re-application** of work already landed, plus the one missing piece (`0060`).

| Signal | `fix/db-perf-consolidation` | `worktree-postgres-split` |
|--------|-----------------------------|----------------------------|
| Has tests for the change | Yes — `test_session_factories.py`, `test_relation_evidence_promoter.py` updated (statement_timeout + promoter) | Split tip adds no new tests beyond shared docs/init-test scripts |
| Updates docs | Yes — design audit + gitops diff + `knowledge-graph.md` + `.claude-context.md` | Design audit + gitops diff only (no service-doc / context updates on the split tip) |
| Migrations clean | Yes — provides missing `0060`, chains 0059→0060→0061 | No `0060`/`0061` at all |
| statement_timeout backstop | Yes | No |
| Wires all OLAP-bound services | Yes (KG, NLP, intel-migrations) | Yes (same content) |
| Rollback path | Yes — idempotent init (old volumes unaffected); gitops diff is reversible; revert is a single revert of `2dabab46b` | Same split content, but buried under 9 unrelated commits |
| PRD/PLAN reference | No dedicated PLAN; design doc `2026-06-08-postgres-workload-split.md` is the spec. No OLAP/split PLAN in `docs/plans` or `docs/specs` | Same |
| Recency / base | Merge-base `37ecd4e3b` (very recent) | Merge-base `9f3cab378` (2026-05-20, stale) |

No PLAN/PRD governs this change — it is driven by the `2026-06-08-postgres-workload-split.md` audit. If integrated, it is worth promoting that audit to a tracked PLAN for the data-migration/cutover steps.

---

## 4. Conflict / integration cost vs HEAD

**`fix/db-perf-consolidation`: LOW.**
- Merge-base is recent (`37ecd4e3b`); only 3 commits to bring over.
- Files it touches that HEAD also recently changed:
  - `infra/compose/docker-compose.yml` — last touched on HEAD by the frontend-sprint consolidation merge (`8ebf6c7f2`). Some manual conflict possible but localized to the new `postgres-intelligence` block + a few `depends_on`/env lines.
  - `services/knowledge-graph/src/knowledge_graph/config.py` — last touched on HEAD by `e26bf249c` (the same statement_timeout work), so the fix-branch version is largely already present; resolve by keeping the superset.
  - `0060`/`0061` migrations — `0060` is purely additive (HEAD lacks it); `0061` already on HEAD (take one copy; they are equivalent).
- Net: a focused, reviewable merge. Most "conflicts" are because HEAD already has a sibling copy of the perf work.

**`worktree-postgres-split`: PROHIBITIVE.**
- 1,251 files / +168k lines, merge-base a month stale. Merging would attempt to re-apply PLAN-0104, CI, observability, and PR #16/17/18 history that is already (differently) on HEAD → massive conflict surface, un-reviewable, high regression risk. There is zero reason to pay this cost since the split content is identical to the fix branch's.

---

## 5. Risk (deploy-topology change)

- **New instance changes deploy topology and every intelligence/KG read path.** All KG path-insight / RAG-chat graph reads and NLP DB access move to `postgres-intelligence`. If half-applied (compose updated but gitops `env/dev` not, or vice-versa), KG/NLP services point at a DB that has no data or doesn't exist → startup failures or empty graph.
- **Data migration is NOT automated.** The commit explicitly leaves "data migration / restart steps for human confirmation." `intelligence_db`, `nlp_db`, `kg_db` (incl. the AGE `worldview_graph`) must be `pg_dump`/`pg_restore`'d from the OLTP instance into `postgres-intelligence` before cutover, or re-created empty and re-ingested. The init scripts only create empty DBs + extensions.
- **Staging:** there is no feature flag, but the change is naturally stageable because the runtime DB host comes from `env_file`/gitops env, not hardcoded. You can: (a) merge compose + bring up `postgres-intelligence` alongside the OLTP instance, (b) migrate data, (c) flip the three service env vars, (d) restart KG/NLP/intel-migrations. Rollback = flip env vars back to `postgres` and restart (old DBs remain on the OLTP instance until explicitly dropped).
- **Migration-chain hazard during integration:** before/after merging, verify `alembic heads` for `intelligence_db` resolves to a single head and the duplicate-`0049` collision on HEAD is resolved (the density index should exist exactly once, as `0060`). Run `alembic upgrade head` against a fresh `postgres-intelligence` to confirm 0059→0060→0061 applies cleanly (the commit claims this was validated in isolation).

---

## Recommended integration approach

1. **Merge `fix/db-perf-consolidation` into `feat/md-reliability-followups`** (normal `git merge`; it is only 3 commits on a recent base). Do not rebase/cherry-pick from `worktree-postgres-split`.
2. **During merge resolution:**
   - Keep HEAD's existing `config.py` statement_timeout + promoter (they match the fix branch); just ensure the fix-branch superset wins where they differ.
   - Take the new `0060_index_relation_evidence_raw_density.py` from the fix branch (HEAD is missing it).
   - **Resolve the duplicate-`0049` collision on HEAD** — the relation_evidence_raw density index must exist exactly once; with `0060` added, drop/neutralize the stray `0049_index_relation_evidence_raw_density.py` so `alembic heads` returns a single linear head 0048→0049→…→0059→0060→0061.
   - Merge the `postgres-intelligence` block + `depends_on`/env repointing into HEAD's compose.
3. **Validate:** `alembic upgrade head` against a throwaway `postgres-intelligence`; run KG + NLP unit tests (`test_session_factories.py`, `test_relation_evidence_promoter.py`); `docker compose config` to confirm the new service parses.
4. **Promote the design audit to a tracked PLAN** covering the cutover runbook (dump/restore of intelligence_db/nlp_db/kg_db incl. AGE graph, gitops `env/dev` host flip, restart order, rollback). The gitops env/dev change is **manual** (`docs/audits/postgres-split-gitops.diff`) and must not be pushed from this repo.
5. **Stage the cutover** rather than big-bang: bring `postgres-intelligence` up alongside OLTP, migrate data, flip the three env vars, restart KG/NLP/intel-migrations, verify graph reads, then (later) drop the moved DBs from the OLTP instance.

### Key commits / files
- Take: `2dabab46b` (split), `33e94b699` (0060 + statement_timeout), `99b120113` (0061 + promoter) from `fix/db-perf-consolidation`.
- Core files: `infra/compose/docker-compose.yml`, `infra/postgres/init-intelligence/*`, `infra/postgres/init/init-databases.sh`, `services/{knowledge-graph,nlp-pipeline}/configs/*.env.example`, `services/intelligence-migrations/configs/prod.env.example`, `services/intelligence-migrations/alembic/versions/0060_*.py`, KG/NLP `config.py` + `*/session.py`, `docs/audits/2026-06-08-postgres-workload-split.md`, `docs/audits/postgres-split-gitops.diff`.
- Ignore entirely: `worktree-postgres-split` (stale; split content already provided by the above).
