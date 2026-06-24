# Root-Cause Investigation — Three Platform Degradations (2026-06-21)

**Date**: 2026-06-21
**Author**: Principal Reliability Engineer (read-only RCA)
**Branch**: feat/frontend-enhancement-sprint
**Scope**: WHAT CAUSED the three degradations restored in `docs/audits/2026-06-21-qa-live-running-instances-report.md` (F-001/002/003) — trigger + contributing factors, not just symptoms.
**Method**: READ-ONLY. Evidence from `docker inspect`, compose source, git reflog/ancestry, BUG_PATTERNS, and the QA report. No mutations.

---

## TL;DR

| ID | Degradation | Trigger (root cause) | Class |
|----|-------------|----------------------|-------|
| **D1** | MinIO OOM-killed (Exit 137) at 12:57:58Z | Docker VM memory exhaustion during a heavy rebuild/recreate wave; **MinIO is the only stateful service with NO memory reservation or limit**, so it was the sacrificial victim. Disk/IO stall (`drive offline`) was a *symptom* of the same VM-wide resource starvation, not an independent cause. | Resource-budget / missing-reservation |
| **D2** | portfolio/market-data/alert stuck `Created` | Migrate sidecars exited non-zero → `depends_on: …: service_completed_successfully` makes compose **create but never start** the API container. Sidecars failed because the **shared dev DBs were stamped ahead of this branch's migration set** (sibling sessions applied `alert 0010`, `market-data 040/041`) **plus** three real bugs in portfolio `0025/0026/0027`. | Shared-dev-DB concurrency + deploy mechanics |
| **D3** | Stale api-gateway image hid the beta/alpha fix | Pure **image-staleness**: the running image was built from a tree (or never rebuilt after) a point predating the verified rebuild. **Refuted**: the worktree resets did NOT revert `risk_metrics.py` — `2ea10ac6d` is an ancestor of every reset target and `_parse_iso_date` was present throughout. | Deploy mechanics / per-variant image drift |

**Common thread**: all three are *operational/deploy* failures amplified by a **shared worktree + shared dev DB + concurrent sibling sessions** running memory-heavy rebuilds, against a compose topology where **only Kafka has resource guarantees** and where **failed/stale deploy state is left silently in place** (created-not-started containers; stale per-variant images).

---

## D1 — MinIO OOM-killed (F-001)

### Evidence
- `docker inspect worldview-minio-1`: `FinishedAt=2026-06-21T12:57:58.97Z`, restarted `StartedAt=2026-06-21T18:33:48Z` (the QA restoration). **`MemLimit=0`** (no limit), `RestartCount=0` (no auto-restart configured for the OOM).
- Last MinIO logs (per QA report): `taking drive /data offline: unable to write+read for 1m37s` immediately before the kill — a **disk/IO stall**, not a clean OOM message from MinIO itself.
- Compose (`infra/compose/docker-compose.yml` L32–50): the `minio:` service has **no `deploy.resources` and no `mem_limit`**. The only memory governance in the file is on **kafka** (L188–194: `reservations: 5G, limits: 6G`, added by `4400b7e92` on 2026-06-20).
- ML containers (`ollama` L1267, gliner) have **GPU-passthrough `deploy` blocks commented out and NO CPU/memory caps** — the PLAN-0113 W1 ML caps were never applied.
- Docker VM: `TotalMemory=50163867648` (~46.7 GiB), `NCPU=14`.
- `scripts/rebuild_service.sh` and `docs/ops/docker-build-hygiene.md` both explicitly state **"The host has OOM'd during mass rebuilds"** — a known, documented condition on this machine.

### Root cause (trigger + contributing factors)
**Trigger**: Docker-VM-wide memory exhaustion at ~12:57Z during the session's family-by-family rebuild/recreate wave. With a 46.7 GiB VM, the simultaneous load — Kafka now *reserving 5 GiB / capped at 6 GiB* (new this session), uncapped `ollama`+`gliner` inference, ~40+ service containers, **plus a no-cache BuildKit build writing layers** — drove the VM into reclaim/OOM. The Linux OOM killer (and/or Docker Desktop's VM memory pressure) selected a victim.

**Why MinIO specifically (the decisive contributing factor)**: MinIO is the **only stateful infra service with no memory reservation and no limit**. Kafka now has a *reservation* that protects it; the ML containers are large but the OOM scoring + MinIO's large page-cache/buffer footprint under IO made MinIO the highest-`oom_score` victim. The "drive offline: unable to write+read for 1m37s" is the **signature of the same starvation**: under VM memory pressure + concurrent build-layer disk writes, MinIO's IO to `/data` stalled past its 1m37s self-health threshold, it took the drive offline, and the process was then killed (Exit 137). So **memory pressure is the dominant trigger; the disk/IO stall is a downstream symptom of the same event**, not an independent disk-full cause.

**Disk contribution (secondary)**: the session's `docker system df` (per the prompt: 163 GB images + 97 GB volumes + 35 GB build cache) means the no-cache builds were writing large layers concurrently, adding **IO contention** on top of memory pressure — which is exactly what tips a memory-starved MinIO past its read/write-timeout into "drive offline". (Live `docker system df` during this RCA hung — itself a sign the daemon is under load.)

### Classification
**Resource-budget / missing-reservation defect.** Asymmetric resource governance: the broker got hardened this session (`4400b7e92`) but the sum of container limits/reservations was never reconciled against the 46.7 GiB VM, and stateful MinIO was left ungoverned — guaranteeing it as the OOM victim under the very rebuild waves the ops docs already warn cause OOM.

---

## D2 — portfolio / market-data / alert API tiers stuck `Created` (F-002)

### Evidence
- Compose `portfolio:` (L319–334) declares `depends_on: portfolio-migrate: condition: service_completed_successfully` (same pattern for market-data/alert). `portfolio-migrate` (L305–316) runs `alembic upgrade head`, `restart: "on-failure:5"`.
- Migrate sidecars now `exited exit=0` (restored 2026-06-21T18:34Z during QA) — they were left failed before that.
- Migration-file provenance (`git log -- <file>`): `alert 0010`, `market-data 040/041`, and the portfolio `0025` *guards* all first appear **only in `37ecd4e3b`** ("resolve alembic migrate-divergence", 2026-06-21 11:18 PDT). The commit message itself documents the cause: alert_db stamped `0010` and market_data_db stamped `041` while this branch's heads were `0009`/`039` — **"the … migration lives only on sibling branch 939c17477 / 90ff92ab4; its DDL was already applied"**. Portfolio `0025–0027` had three real bugs (non-idempotent ADD COLUMN → DuplicateColumnError; wrong column name; non-IMMUTABLE CAST in a functional index).
- Sibling worktrees exist on disk: `.claude/worktrees/agent-a428032d107ca6b5b/`, `.claude/worktrees/db-perf-consolidation/` — confirming concurrent sessions sharing the dev Postgres.
- `scripts/rebuild_service.sh` L130: recreate uses `up -d --force-recreate --no-deps "${SERVICES[@]}"`.

### Root cause (the full chain)

**Link 1 — why the DBs were stamped ahead of this branch's images.** The dev Postgres instances are **shared across all concurrent worktrees/sessions**. A sibling session on branch `939c17477` (alert) and `90ff92ab4` (market-data) ran `alembic upgrade head` against the *same* `alert_db` / `market_data_db`, **stamping `alembic_version` at `0010` / `041` and applying the DDL** — but those revision *files* lived only on the sibling branch. When this branch's migrate sidecar booted, alembic found the DB at a revision **its own `versions/` directory did not contain** → `Can't locate revision` / `KeyError`. For portfolio, a sibling applied the cost-basis ADD COLUMN DDL *without the stamp matching this branch's files*, so this branch's non-idempotent `0025` then hit `DuplicateColumnError`. **Mechanism: shared mutable dev DB + per-branch migration files = the DB can be at a revision your image's code cannot resolve or re-apply.**

**Link 2 — why failure left the container `Created` (not started, not errored-away).** Compose `depends_on … condition: service_completed_successfully` means the API service starts **only if** its migrate dependency exits 0. The migrate sidecars exited 1 (after exhausting `restart: on-failure:5`). Compose therefore **creates the API container object but never starts it** — leaving it permanently in `Created`. This is exactly the documented behavior; the QA report's hypothesis is confirmed by the compose source. No error is surfaced to the operator beyond the sidecar's non-zero exit, which is easy to miss in a multi-service `up`.

**Link 3 — why the rollout never caught/restarted them.** The session's Kafka-resilience rollout recreated **dispatchers/consumers** via `rebuild_service.sh`, which runs `up -d --force-recreate --no-deps`. The **`--no-deps` flag bypasses the migrate sidecars and the API tiers entirely** — so the rollout neither re-ran the migrations nor (re)started the API containers. The broken `Created` state from the earlier failed migrate was simply never revisited until QA ran `up -d portfolio market-data alert` explicitly.

### Classification
**Concurrency (shared-dev-DB) defect + deploy-mechanics gap.** Trigger = sibling sessions migrating the shared DBs out from under this branch (links the orphan stamps) compounded by portfolio's own non-idempotent migrations. Contributing = `service_completed_successfully` silently parks the API container, and `--no-deps` recreates bypass the tier so nothing self-heals.

---

## D3 — Stale api-gateway image hid the beta/alpha fix (F-003)

### Evidence
- Risk fix `2ea10ac6d` ("risk-metrics benchmark parse … BP-682"): authored & committed **2026-06-20 10:04:24 -0700** (= 17:04Z).
- Running api-gateway at QA time lacked `_parse_iso_date` (beta/alpha null). After QA's rebuild: **`worldview-api-gateway` image `Created=2026-06-21T18:39:49Z`**, container recreated `2026-06-21T18:40:01Z`, started `18:40:12Z` → beta/alpha restored (1.1218 / 1.7067).
- **Worktree resets did NOT revert the fix** (refutes the BP-590-revert hypothesis):
  - `git merge-base --is-ancestor 2ea10ac6d 5fa5296c0` → **YES** (the reset target `5fa5296c0` *contains* the fix).
  - `git merge-base --is-ancestor 2ea10ac6d 38fc4f788` → **YES** (the other reset target also contains it).
  - `git grep -c _parse_iso_date 5fa5296c0 -- …/risk_metrics.py` → **3** (present at the reset target).
  - The reflog shows ~7 `reset: moving to HEAD` entries on 2026-06-20 (11:12–13:27 PDT) all landing on `5fa5296c0`/`38fc4f788` — **all of which are descendants of the risk fix**. So at no committed point after 06-20 10:04 did HEAD's `risk_metrics.py` lose `_parse_iso_date`.
- `_parse_iso_date` is present in current HEAD (`17d72e5ac`) and a regression test exists (`tests/test_risk_metrics_wave_g.py::test_parse_iso_date_accepts_datetime_and_bare_date`).
- `docs/ops/docker-build-hygiene.md` §"Second failure mode" documents: **a mass parallel BuildKit build can crash ("frontend grpc server closed unexpectedly") under memory pressure, return success-ish, and leave STALE images** — "The host has OOM'd during mass rebuilds."

### Root cause (trigger + contributing factors)
**Trigger**: the api-gateway *image* the platform was running at QA time was **built from a tree predating `2ea10ac6d`, or api-gateway was simply never rebuilt after that commit on this machine** — a pure **deploy-staleness** condition. The committed-and-tested source code was always correct (proven above); only the **baked image** lagged HEAD.

**Most likely mechanism** (ranked):
1. **The "verified live earlier" rebuild happened in a sibling worktree / different stack, or was a transient build that a later recreate overwrote.** Because the worktree is shared and sibling sessions run `make dev` / bulk recreates with `--force-recreate`, a `up -d --force-recreate` that does **not** rebuild will **recreate the api-gateway container from whatever `worldview-api-gateway:latest` currently exists** — which may be an *older* image if the verifying rebuild's image was superseded or never persisted as `:latest` in this stack. `--force-recreate` recreates the *container*, not the *image*; it does not pick up source changes.
2. **A mass/parallel rebuild during the session hit the documented BuildKit-grpc crash under the same memory pressure that OOM-killed MinIO (D1), returning while leaving api-gateway's image stale** — the exact "second failure mode" in the hygiene doc.

**Refuted hypothesis**: "a BP-590 worktree reset reverted `risk_metrics.py` and a subsequent rebuild baked the reverted version." Git ancestry disproves it — every reset target is a *descendant* of the fix and contains `_parse_iso_date`. The regression was in the **image layer, never the git layer**.

### Classification
**Deploy-mechanics defect (per-variant image staleness), amplified by shared-worktree concurrency and the same memory pressure as D1.** Not a source/VCS regression.

---

## Cross-Cutting Common Causes

1. **Shared worktree + shared dev DB + concurrent sibling sessions.** Directly causes D2 (sibling migrations stamp the shared DBs ahead of this branch) and is the most likely amplifier of D3 (sibling recreates/builds toggling `:latest`). The reflog's repeated `reset: moving to HEAD` and the two `.claude/worktrees/*` directories are the fingerprints (consistent with the BP-590 resets the prompt notes).
2. **Asymmetric resource governance.** Only Kafka has a reservation/limit. MinIO (stateful) and the ML containers (huge) are ungoverned on a 46.7 GiB VM → MinIO is the deterministic OOM victim (D1), and memory-pressure BuildKit crashes leave stale images (D3). The ops docs already *warn* "the host has OOM'd during mass rebuilds" — the warning was never converted into limits.
3. **Deploy mechanics that silently leave bad state in place.**
   - `depends_on: service_completed_successfully` + a failed migrate ⇒ API container **`Created`, never started, no loud error** (D2).
   - `up -d --force-recreate --no-deps` recreates the **container from the existing image** and **skips dependencies** ⇒ stale image keeps serving (D3) and broken tiers are never revisited (D2 link 3).
   - Per-variant images mean "a committed fix is not deployed until *that specific image* is rebuilt" (D3, and the hygiene doc's whole reason to exist).
4. **No post-deploy "running image == HEAD" verification.** Nothing checks that the live api-gateway image was built from current source, so a stale image served wrong numbers for hours until a human QA pass noticed.

---

## Prevention Recommendations (ranked by leverage)

1. **Add memory reservations + limits to MinIO and the ML containers; reconcile the total against the VM budget.** Give `minio` a `deploy.resources` reservation (e.g. 1–2G reserve / 3G limit) and `oom_kill_disable`-aware sizing, and finally apply the commented PLAN-0113 W1 caps on `ollama`/`gliner`. Sum all reservations and assert `< VM_TOTAL − headroom`. *Directly prevents D1; reduces D3's BuildKit-crash trigger.* **Highest leverage.**
2. **Migrate-on-shared-DB protocol.** Either (a) give each worktree/branch its own Postgres (per-branch DB name or container), or (b) forbid sibling sessions from running `alembic upgrade head` against the shared dev DBs, or (c) make every migration **idempotent + guarded** (inspector existence checks, `IF NOT EXISTS`) and never stamp DDL that isn't on the branch. *Prevents D2 link 1.* The portfolio `0025–0027` bugs also argue for a **migration lint** (no non-idempotent ADD COLUMN, no non-IMMUTABLE functional-index expressions, `sa.text()` for raw SQL) in the migration-guard hook.
3. **Post-deploy "running image == HEAD" verification.** After any rebuild, bake the git SHA into the image (`ARG GIT_SHA` → `/version` endpoint or image label) and a CI/ops check that asserts the **running** api-gateway/service `/version` == `git rev-parse HEAD`. *Catches D3 in seconds instead of hours.*
4. **Make failed-migrate state loud and self-correcting.** Add a deploy post-step (or `make rebuild`) that, after recreate, runs `docker compose ps` and **fails if any expected service is `Created`/exited-non-zero** (especially `*-migrate`). Consider not using `--no-deps` for the API tiers, or a separate `make migrate` gate that must pass before the API tiers are brought up. *Prevents D2 links 2 & 3 from going unnoticed.*
5. **Worktree/session mutual exclusion for deploy + DB ops.** Enforce `scripts/worktree_lock.sh acquire` (already referenced in CLAUDE.md) around any `make dev` / bulk rebuild / `alembic upgrade` so two sessions can't recreate containers or migrate the shared DB concurrently. *Reduces D2 and D3 root concurrency.*
6. **Never mass-parallel-build; keep sequential builds + retry-on-grpc-crash detection.** `rebuild_service.sh` already builds sequentially; add an explicit check that each `compose build` actually produced a newer image ID (compare image `Created` before/after) and fail loudly if not. *Closes D3's "BuildKit returned but image is stale" mode.*

---

## Compounding (suggested BUG_PATTERNS / docs follow-ups)

- New BP: **"`depends_on: service_completed_successfully` + failed migrate ⇒ API container stuck `Created`, silently un-started"** — with the fix being a post-recreate `docker compose ps` gate. (D2)
- New BP: **"Shared dev DB stamped ahead of branch's `versions/` ⇒ migrate sidecar `Can't locate revision`; sibling sessions migrating the same Postgres."** (D2 link 1) Cross-link `37ecd4e3b`.
- New BP / extend the hygiene doc: **"`--force-recreate` recreates the container from the existing image, not from source — a stale `:latest` keeps serving until rebuilt; verify running image == HEAD via baked GIT_SHA."** (D3)
- Extend `docs/ops/docker-build-hygiene.md` with the **MinIO-OOM-victim** note: ungoverned stateful service on a memory-pressured VM is the first to die during rebuild waves — add resource reservations. (D1)
- Reinforce the existing QA-report compounding line: *a committed fix is not deployed until the specific per-variant image is rebuilt, and a failed migrate aborts the API tier into `Created` while a stale image keeps serving.*
