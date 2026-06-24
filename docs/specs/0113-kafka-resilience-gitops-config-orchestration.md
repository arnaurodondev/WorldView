# PRD-0113 — Kafka Resilience (DEV tuning / PROD scale-out) + GitOps Config-Orchestration Model

**Status**: Draft
**Author**: Arnau Rodon (with Claude)
**Created**: 2026-06-16
**Branch**: `feat/frontend-enhancement-sprint`
**Repos touched**: `worldview` (code + dev infra) **and** `worldview-gitops` (prod/dev config) — see §6.1
**Grounding investigation**: Live LOCAL-DEV incident, 2026-06-16 — single-node KRaft Kafka
QuorumController event-queue overload (`REQUEST_TIMED_OUT` heartbeats, "controller event queue
overloaded") under ~291 partitions on one broker + a simultaneous 5-heavy-consumer rebalance storm +
host-CPU starvation by `gliner-server`/`ollama`. Recovery required pausing the CPU hogs and starting
consumers one at a time.

> **Read this framing first.** DEV and PROD need **opposite** answers and this PRD must not blur them.
> - **DEV = a single host.** Adding Kafka brokers *hurts* (more controller/replication load on the same
>   CPU). The fix is **tuning down**: fewer partitions, static consumer membership, CPU isolation so ML
>   inference cannot starve Kafka/Postgres.
> - **PROD = a real k8s cluster** (Hetzner, `node-role: stateful`, Bitnami Kafka chart 32.4.3). There
>   multi-broker **is** the correct scaling lever and the gitops layer already supports it declaratively.
>   **This PRD takes that lever now (DECIDED, OQ-3/OQ-4): prod Kafka moves to 3 brokers
>   (`broker.replicaCount: 3`) with `replicationFactor: 3` and a dedicated controller
>   (`controller.controllerOnly: true`).** This is the deliberate prod scale-out the asymmetry calls for.
> The design serves both from gitops **wherever config can**, and is explicit about the one thing that
> cannot live in gitops — the FIX-2 application **code** (`group.instance.id`).

---

## 1. Problem Statement

The platform's event backbone (single-node KRaft Kafka) became **unrecoverable in local dev** during a
routine bring-up. Three independent factors compounded:

1. **Too many partitions for one broker.** `infra/kafka/init/create-topics.sh` declares **212 application
   partitions** across 23 topics (verified by summing the spec, plus the compacted `entity.dirtied.v1`
   at 24), and Kafka's internal `__consumer_offsets` adds 50, for **~286–291 partitions on a single
   KRaft node**. Each partition is leader+follower metadata the lone QuorumController must heartbeat and
   reconcile. On a laptop-class host this is enough to overload the controller event queue on its own.

2. **A simultaneous rebalance storm.** The five heavy NLP consumers — 3× `nlp-pipeline-article-consumer`
   (via `deploy.replicas: 3`), `nlp-pipeline-relevance-scoring`, and `nlp-pipeline-embedding-retry-worker`
   — all join their groups at once on `make dev`. Even with **cooperative-sticky already enabled**
   (`ConsumerConfig.partition_assignment_strategy = "cooperative-sticky"`,
   `libs/messaging/src/messaging/kafka/consumer/base.py:293`), a cold simultaneous join is still N group
   joins racing the already-overloaded controller. Members churn in/out (`SESSTMOUT`), each churn is
   another controller event.

3. **CPU starvation by ML inference.** `gliner-server` and `ollama` routinely consume 200 %+ CPU and have
   **no resource limits** in `infra/compose/docker-compose.yml` (the `deploy.resources` blocks are
   commented out — lines ~1185 and ~1261). When the host is saturated, the Kafka container loses its CPU
   slice; controller heartbeats time out; the queue backs up further. A feedback loop.

We recovered only manually (pause CPU hogs, start consumers one at a time). This is not reproducible,
not declarative, and **wrong for the architecture**: the dev failure is a *too-much-for-one-host*
problem, while the prod posture is the *opposite* (scale horizontally). Today both environments are
driven from effectively one configuration, so we cannot tune them independently.

### Two latent gitops gaps this incident exposed

Beyond the three fixes, the incident surfaced two structural problems in how config is orchestrated:

- **GAP-1 — Dev config has two sources of truth that can silently drift.** `worldview-gitops/env/dev/<svc>.env`
  is the *authoritative authored* dev config, but Docker Compose reads
  `worldview/services/<svc>/configs/docker.env` (e.g. `docker-compose.yml:1363`). The link between them is a
  **one-shot copy** (`worldview-gitops/scripts/setup-dev.sh`: `cp env/dev/<svc>.env →
  ../worldview/services/<svc>/configs/docker.env`). Any tuning applied directly to `docker.env` (exactly
  what we did during recovery) is **lost on the next `setup-dev.sh` run** and never flows back to gitops.
  There is no drift check.

- **GAP-2 — There is no prod overlay.** Each service has exactly one `worldview-gitops/values/<svc>.yaml`
  referenced by its ArgoCD app (`valueFiles: [../../values/<svc>.yaml, secrets...]`). FIX-1 (partitions)
  and FIX-3 (resources) **force** dev/prod divergence (dev tiny, prod large). With a single values file
  there is nowhere to express "1 partition in dev, 12 in prod" cleanly — the same file would have to be
  both. (`infra-kafka.yaml` already diverges by env by hand in its `extraConfig`; we need a general
  mechanism.)

### Why now
The dev flood is reproducible and blocks reliable local bring-up (the daily inner loop and the thesis
demo path). The fixes are low-risk and additive (cooperative-sticky is already shipped, so no risky
assignor migration). Resolving the two gitops gaps now also unblocks every future env-divergent change.

---

## 2. Target Users & Journeys

| User | Journey | Today | After |
|------|---------|-------|-------|
| **Developer (local)** | `make dev` cold start | Controller overload; manual recovery (pause ML, hand-start consumers) | Clean, deterministic bring-up; ML capped; consumers join without storming the controller |
| **Developer (local)** | Tune a dev setting (e.g. consumer count, a threshold) | Edits `docker.env`; lost on next `setup-dev.sh`; gitops drifts | One authoritative dev source; a drift check fails loudly if they diverge |
| **Operator (prod)** | Scale a hot consumer | Deployment replicas get random pod names → static membership buys nothing | StatefulSet-backed consumers with stable `name-0/1/2` identity → static membership pays off; brokers scale via Bitnami values |
| **Operator (prod)** | Provision a new topic | Auto-create with broker-default partitions (no declarative record) | Declarative Bitnami `provisioning.topics` — partitions/RF are reviewed in git |
| **Thesis** | Defend an env-aware deployment model | Single config blurs dev/prod; failure narrative is "we tuned by hand" | Documented code/config split + dev-vs-prod overlay model — a defensible operations contribution |

---

## 3. Requirements

### 3.1 Functional — Must-have (v1)

**FIX 1 — Partition counts (env-divergent).**
- **FR-1 (DEV)**: Reduce application-topic partition counts in `infra/kafka/init/create-topics.sh` so the
  single KRaft node carries far fewer partitions. Target per-topic: **1** for low-volume topics, **3** for
  the genuinely parallel high-volume topics (the article/enriched/signal pipeline). Goal: **≤ ~40 app
  partitions** total in dev (from 212), keeping `__consumer_offsets` the dominant remaining cost.
- **FR-2 (PROD)**: Add **declarative topic provisioning** to `worldview-gitops/apps/infra-kafka.yaml` via the
  Bitnami chart's `provisioning.enabled: true` + `provisioning.topics[]` (name / partitions /
  replicationFactor / config). **Every provisioned topic uses `replicationFactor: 3`** (DECIDED — prod moves
  to 3 brokers, OQ-3). Set broker defaults by **appending** `num.partitions`,
  `offsets.topic.num.partitions`, **and `default.replication.factor`/`offsets.topic.replication.factor`/
  `transaction.state.log.replication.factor` (all `= 3`)** to the **existing** `extraConfig` block (verified
  this session: `infra-kafka.yaml` already has an `extraConfig:` literal carrying `log.retention.hours=720` /
  `log.retention.bytes` / `message.max.bytes` — do NOT overwrite it; append the new lines). Prod partition
  counts are the *current* (higher) values, sized for multi-broker. **Today infra-kafka.yaml has no
  `provisioning` block** (auto-create) — that block is net-new. **RF-migration caveat**: existing prod
  topics are RF=1 and Helm/provisioning **cannot raise RF on an already-existing topic** — see §9 and the
  Wave 5 runbook note; the RF=3 values apply cleanly only to net-new topics or a fresh cluster.
- **FR-3 (consistency)**: Topic names + per-env partition counts are the single declarative record. The dev
  shell script and the prod provisioning list must enumerate the **same topic set** (a test asserts parity
  of names; counts may differ by env).

**FIX 2 — Static consumer membership (`group.instance.id`).** Cooperative-sticky is already on; this is
purely additive (no assignor migration).
- **FR-4 (library, CODE — cannot live in gitops)**: Add an optional `group_instance_id: str = ""` field to
  `ConsumerConfig` (`libs/messaging/.../consumer/base.py`). `to_dict()` emits `"group.instance.id"` **only
  when the value is non-empty** (backward-compatible: every consumer that doesn't set it behaves byte-for-byte
  as before — same pattern as the existing `enable_persistent_retry` default-off design).
- **FR-5 (service config, CODE)**: Each of the **7 consumer-running** `services/*/config.py` gains a
  `kafka_<scope>_consumer_instance_id: str = ""` pydantic setting (env-prefixed, default empty). Default-empty
  preserves current behaviour everywhere it is not wired. (Verified this session: the services that actually
  instantiate `ConsumerConfig` are **alert, content-ingestion, content-store, knowledge-graph, market-data,
  nlp-pipeline, portfolio**. `market-ingestion`, `api-gateway`, and `rag-chat` have **zero** `ConsumerConfig`
  call sites — they are NOT touched by FIX-2.)
- **FR-6 (instantiation sites, CODE)**: The **38** `ConsumerConfig(...)` call sites pass the matching
  instance-id setting through. Where empty, no change in behaviour. Site distribution (verified
  `git grep -n "ConsumerConfig(" services --include="*.py" | grep -v test` = 38): **28** sites live in
  `*/consumers/*_main.py` entrypoints; the other **10** live outside `_main.py` — `services/alert/main.py`
  (2 sites) and 8 `*_consumer.py` consumer-class files where `ConsumerConfig(...)` is a `if config is None:`
  fallback default (market-data ×6, content-store ×2). The fallback-default sites build a no-arg-group config
  and are exercised only when `_main.py` does not inject one; wiring them is optional in v1 (they remain
  dynamic / empty) — only the `_main.py` sites need the real instance-id pass-through.
- **FR-7 (PROD config, gitops)**: Inject `group.instance.id` from **stable pod identity** via the k8s
  downward API (`valueFrom.fieldRef: metadata.name`). **This requires StatefulSet** (see FR-9) so the name
  is stable across restarts; a Deployment's random pod name changes on restart and static membership would
  buy nothing.
- **FR-8 (DEV config, gitops→compose)**: Provide a **stable per-replica** instance id in dev. Because
  `deploy.replicas: 3` gives all three replicas the *same* env (→ identical `group.instance.id` → fencing),
  v1 **replaces the scaled `deploy.replicas` block for static-membership consumers with explicit numbered
  services** (`nlp-pipeline-article-consumer-0/1/2`), each setting a distinct
  `*_INSTANCE_ID=article-consumer-0|1|2`. (Alternative considered + rejected in AD-2.)

**FIX 2 infra dependency — StatefulSet variant (PROD, gitops chart).**
- **FR-9 (chart, gitops)**: The shared `charts/worldview-service` gains a **StatefulSet workload variant**
  (gated by `kind: StatefulSet` or `statefulSet.enabled: true` in values), rendering a headless Service and a
  StatefulSet so multi-replica consumers get stable `name-0/1/2` identities. Single-replica API/services keep
  the existing Deployment. This is a **chart change**, not just a values change.

**FIX 3 — CPU isolation (env-divergent).**
- **FR-10 (DEV)**: Add `deploy.resources.limits` + `deploy.resources.reservations` (CPU + memory) to
  `infra/compose/docker-compose.yml` for `gliner-server`, `ollama`, `kafka`, and `postgres` so ML inference
  cannot starve Kafka/Postgres. Reserve guaranteed CPU for `kafka` + `postgres`; cap `gliner`/`ollama`.
- **FR-11 (DEV)**: Cap the consumer fan-out (the numbered article consumers from FR-8 default to a count that
  matches the reduced dev partition count, e.g. 1–2, not 3, since dev partitions drop in FR-1).
- **FR-12 (PROD)**: Right-size ML-service `resources` in gitops values (most app services already have
  `requests`/`limits`; `infra-ollama.yaml`/`infra-kafka.yaml` already carry resources). Audit + adjust;
  ensure Kafka has guaranteed CPU headroom relative to ML pods on the same nodes.

**GitOps orchestration model (resolves GAP-1 + GAP-2).**
- **FR-13 (code/config split, documented)**: The PRD + a new gitops doc state explicitly: gitops owns **all
  config** (env, resources, broker config, topic provisioning, replica counts, instance-id injection); gitops
  **cannot** own the FIX-2 **application code** (the `group_instance_id` field + plumbing) — that ships in
  `worldview`. Implementers must touch both repos for FIX-2.
- **FR-14 (GAP-1 — single dev source of truth)**: `worldview-gitops/env/dev/<svc>.env` is declared the **sole
  authoritative** dev config; `worldview/services/<svc>/configs/docker.env` is a **generated artifact**. Add
  (a) a drift check (`scripts/check-dev-env-drift.sh` in gitops, or a worldview Makefile target) that fails if
  any `docker.env` differs from its `env/dev/` source, and (b) a header banner in each generated `docker.env`
  ("GENERATED — edit env/dev/<svc>.env in worldview-gitops, run setup-dev.sh"). v1 keeps the copy mechanism
  (low-risk) but makes drift loud. (Symlink alternative rejected in AD-4.)
- **FR-15 (GAP-2 — prod overlay scheme)**: Introduce a base + prod-overlay values layout:
  `values/<svc>.yaml` (base / dev-safe defaults) **+** `values/<svc>.prod.yaml` (prod overrides — higher
  replicas/resources, `statefulSet.enabled` for consumers), referenced in each ArgoCD app's `valueFiles`
  (later file wins, mirroring how `infra-kafka.yaml` already hand-diverges by env). **v1 introduces the
  overlay for ALL 7 consumer-running services** (DECIDED, OQ-7: alert, content-ingestion, content-store,
  knowledge-graph, market-data, nlp-pipeline, portfolio) — each gets a `values/<svc>.prod.yaml` overlay wired
  into its ArgoCD app — plus Kafka (`infra-kafka.yaml`, env-diverged in place). The 3 non-consumer services
  (api-gateway, market-ingestion, rag-chat) keep a single values file in v1 (FR-16 covers full migration).

### 3.2 Functional — Nice-to-have (deferred to v2)

- **FR-16**: Migrate **all** 10 services to the base+prod overlay (v1 does only the divergent ones).
- **FR-17**: Replace the dev `docker.env` copy with a Compose `env_file` that points directly at the gitops
  `env/dev/<svc>.env` path (eliminates the copy entirely) — deferred because it couples the two repo
  checkout layouts.
- **FR-18 (PROMOTED TO v1 — DECIDED, OQ-3/OQ-4)**: Prod **multi-broker** broker scaling
  (`broker.replicaCount: 3` + `replicationFactor: 3`) and controller/broker role split
  (`controller.controllerOnly: true`, dedicated KRaft controller) **ship in Wave 5** of v1, not deferred.
  The values flip is declarative in `apps/infra-kafka.yaml`; the only non-declarative part is the RF-migration
  of pre-existing RF=1 topics, which is an **operational runbook** (kafka-reassign-partitions or fresh
  cluster) documented as a Wave 5 note — NOT executed by this PRD (the prod cluster is not reachable here).
- **FR-19**: KEDA / lag-based autoscaling for consumers (the chart's HPA is CPU/mem only and does not fit
  Kafka lag). Deferred.
- **FR-20**: Move `__consumer_offsets` partition count down in dev via `offsets.topic.num.partitions` in the
  dev broker config (the single largest remaining partition contributor after FR-1). Deferred to validate it
  doesn't break the dev KRaft single-node bootstrap.

### 3.3 Non-Functional

- **NFR-1 (DEV stability)**: `make dev` cold start reaches all-consumers-joined with **zero** controller
  `REQUEST_TIMED_OUT` / "event queue overloaded" log lines, with no manual intervention, on a 2024-class
  laptop (≤ 8 performance cores).
- **NFR-2 (DEV resource bound)**: `gliner-server` + `ollama` combined CPU is capped such that `kafka` +
  `postgres` always retain their reserved CPU (verified via `docker stats` during a seed run).
- **NFR-3 (backward compat — code)**: All FIX-2 code changes are additive with empty defaults; every
  consumer not opting in (all 38 sites except the dev article fleet) must produce a **byte-identical** rdkafka
  config dict (existing unit tests for `ConsumerConfig.to_dict()` stay green unchanged — verified: those
  tests assert individual keys, not a full-dict snapshot, so an omit-when-empty addition cannot break them) —
  R5/R11 spirit applied to config.
- **NFR-4 (no secret exposure)**: No change touches `worldview-gitops/secrets/*.yaml` (SOPS-encrypted).
  Instance-id injection uses the downward API, not secrets.
- **NFR-5 (idempotent provisioning)**: Bitnami topic provisioning and the dev `create-topics.sh` both use
  create-if-not-exists semantics; re-running neither errors nor resets partition counts on existing topics
  (Kafka cannot *reduce* partitions — see Failure Modes §9).
- **NFR-6 (reproducibility / thesis)**: Both env partition tables, resource limits, and the code/config-split
  rationale are recorded in docs so the dev-vs-prod posture is reproducible and citable.

### 3.4 Open-question severity
No BLOCKING open questions remain — every code/config claim in this PRD was verified against the actual
files this session (see the verification notes inline in §6). **All 8 prior open questions are now RESOLVED
into firm decisions (§14)**: the formerly-deferred prod scale-out (OQ-3 multi-broker, OQ-4 controller split)
is **taken now** in Wave 5, and the prod-overlay scope (OQ-7) is **all 7 consumer services**. OQ-6
(`offsets.topic.num.partitions` in dev) is the only item kept as DEFER, by decision.

---

## 4. Out of Scope

- Changing the Kafka chart vendor or major version (stays Bitnami 32.4.3).
- Schema Registry / Avro schema changes (no event shapes change here).
- Application logic, domain entities, DB schema, or API endpoints — **this PRD touches only Kafka topology,
  consumer membership config, container resources, and the gitops orchestration model**. No migration.
- Tuning `__consumer_offsets` in dev (FR-20 / OQ-6, deferred).
- Lag-based autoscaling (FR-19, deferred).
- **Executing** the RF-migration of existing prod RF=1 topics (the prod values move to RF=3, but raising RF
  on pre-existing topics is an operator runbook — documented in Wave 5, NOT executed; prod cluster unreachable).
- Editing SOPS secrets.

---

## 5. Success Metrics

| Metric | Baseline (2026-06-16) | Target |
|--------|----------------------|--------|
| App-topic partitions on dev single node | 212 (+24 compacted +50 offsets ≈ 286–291) | ≤ ~40 app (+offsets) |
| Controller "event queue overloaded" / `REQUEST_TIMED_OUT` lines per `make dev` | many (flood) | 0 |
| Manual steps to reach healthy dev | pause ML + hand-start consumers | 0 |
| Kafka/Postgres CPU starvation under ML load | yes (200 %+ ML, no caps) | no (reserved CPU honoured) |
| Consumers fenced/churning on cold start | yes (`SESSTMOUT` loop) | 0 (static membership + capped fan-out) |
| Prod topics with declarative partition record | 0 (auto-create) | all (Bitnami `provisioning.topics`, RF=3) |
| Prod Kafka brokers | 1 (single broker, RF=1) | 3 (`broker.replicaCount:3`, RF=3, dedicated controller) |
| Dev config sources of truth | 2 (drift-prone copy) | 1 authoritative + drift check |
| Services with a prod overlay | 0 | Kafka + all 7 consumer services in v1 |

---

## 6. Technical Design

### 6.1 Affected Services / Repos

| Repo · Area | Change | Why |
|-------------|--------|-----|
| **worldview · `libs/messaging`** | `ConsumerConfig.group_instance_id` field + conditional `"group.instance.id"` in `to_dict()` (FR-4) | Static membership primitive (CODE — cannot live in gitops) |
| **worldview · `services/*/config.py`** (×**7**: alert, content-ingestion, content-store, knowledge-graph, market-data, nlp-pipeline, portfolio) | New `kafka_*_consumer_instance_id` settings (FR-5) | Pydantic-settings env knob per consumer scope (the other 3 services have no `ConsumerConfig` site) |
| **worldview · `ConsumerConfig(...)` call sites** (**38** total: 28 in `*/consumers/*_main.py` + 10 outside — `alert/main.py` ×2, market-data/content-store `*_consumer.py` fallback defaults ×8) | Pass instance-id into `ConsumerConfig(...)` (FR-6) | Wire the knob to the library; fallback-default sites are optional in v1 |
| **worldview · `infra/kafka/init/create-topics.sh`** | Drop dev partition counts to 1–3 (FR-1) | DEV single-host tuning |
| **worldview · `infra/compose/docker-compose.yml`** | Add `deploy.resources` to `gliner-server`/`ollama`/`kafka`/`postgres`; replace `nlp-pipeline-article-consumer` `deploy.replicas:3` with explicit numbered services + per-replica `*_INSTANCE_ID` (FR-8/10/11) | DEV CPU isolation + stable dev membership |
| **worldview-gitops · `apps/infra-kafka.yaml`** | Add `provisioning.enabled` + `provisioning.topics[]` (RF=3); **`broker.replicaCount:3` + `replicationFactor:3` + `controller.controllerOnly:true`**; `extraConfig` `num.partitions`/`offsets.topic.num.partitions`/`default.replication.factor=3`/`offsets.topic.replication.factor=3`/`transaction.state.log.replication.factor=3` (FR-2/FR-18) | PROD declarative topology + multi-broker scale-out |
| **worldview-gitops · `charts/worldview-service/templates/`** | New StatefulSet workload variant + headless Service (FR-9) | Stable pod identity for prod static membership |
| **worldview-gitops · `values/<svc>.yaml` + new `values/<svc>.prod.yaml`** (×**7** consumer services: alert, content-ingestion, content-store, knowledge-graph, market-data, nlp-pipeline, portfolio) | Base + prod overlay for **all 7** consumer services; instance-id `valueFrom.fieldRef`; `statefulSet.enabled` for consumers; right-size resources (FR-7/12/15) | PROD scale-out config + GAP-2 |
| **worldview-gitops · `apps/worldview-<svc>.yaml`** (×**7** consumer services) | Add `values/<svc>.prod.yaml` to `valueFiles` (FR-15) | Wire the overlay into ArgoCD |
| **worldview-gitops · `scripts/` + generated `docker.env` header** | Drift check + GENERATED banner (FR-14) | GAP-1 single source of truth |
| **worldview-gitops · `env/dev/<svc>.env`** | Add the new `*_INSTANCE_ID` + any dev resource knobs (authoritative dev source) | GAP-1: dev knobs live here, copied to `docker.env` |
| **Docs (both repos)** | `docs/libs/messaging.md`, `docs/services/nlp-pipeline.md`, gitops `docs/` (code/config split, overlay model), `docs/BUG_PATTERNS.md`, `docs/plans/TRACKING.md` | R15 |

> **Verified this session**: `ConsumerConfig` (base.py:220–345) has `partition_assignment_strategy=
> "cooperative-sticky"` and `to_dict()` via `apply_base_rdkafka_config`, **no** `group_instance_id`.
> `create-topics.sh` sums to 212 app partitions. `docker-compose.yml` ML `deploy.resources` are commented
> out; `nlp-pipeline-article-consumer` has `deploy.replicas: 3` reading `services/nlp-pipeline/configs/
> docker.env`. `infra-kafka.yaml` has **no** `provisioning` block (`replicaCount: 1`,
> `controller.replicaCount: 1`). The chart has only `deployment.yaml` (no StatefulSet). `apps/worldview-
> nlp-pipeline.yaml` `valueFiles` = `[values/nlp-pipeline.yaml, secrets...]` (no prod overlay).
> `setup-dev.sh` copies `env/dev/<svc>.env → services/<svc>/configs/docker.env` (one-shot, no drift check).

### 6.2 API Changes

**None.** No HTTP endpoint is added, changed, or removed. (R14/R25/R27 not engaged.)

### 6.3 Event Changes

**No new Kafka events and no schema changes.** Topic *names* are unchanged; only **partition counts**
(per env) and **provisioning mechanism** change. Partition count is a topic property, not an Avro schema
property → **R5 (Avro forward-compat) not engaged**; consumers are partition-count-agnostic. Adding
`group.instance.id` changes only consumer-group membership semantics (static vs dynamic), not message
shape or delivery contract → **R8 (no dual writes) not engaged**.

> **Partition-count safety**: Kafka allows *increasing* partitions but never *decreasing* on an existing
> topic. In **dev** the fix lands on a **fresh volume** (the documented `make dev` flow recreates the
> KRaft data dir; existing topics are not silently shrunk — see §9 Failure Modes). In **prod** the
> provisioning list uses the *current* (higher) counts, so nothing shrinks.

### 6.4 Database Changes

**None.** No table, column, index, or Alembic migration. R24 (intelligence_db DDL ownership) not engaged.

### 6.5 Library / Config Model Changes (the substance of this PRD)

#### 6.5a `ConsumerConfig.group_instance_id` (worldview, `libs/messaging`) — FR-4

- **New field**: `group_instance_id: str = ""` (dataclass field, default empty → opt-in, mirrors the
  existing `enable_persistent_retry: bool = False` default-off convention in the same dataclass).
- **`to_dict()` change**: the current method (`base.py:318`) **`return`s `apply_base_rdkafka_config({...})`
  directly** (single expression, no local var — verified this session). The fix must first bind the result
  to a local, then **conditionally** add the key before returning:
  ```python
  cfg = apply_base_rdkafka_config({ ... existing keys ... })  # was: `return apply_base_rdkafka_config(...)`
  if self.group_instance_id:              # empty string => omit entirely
      cfg["group.instance.id"] = self.group_instance_id
  return cfg
  ```
  - **Invariant**: when `group_instance_id == ""`, `to_dict()` returns a dict **byte-identical** to today's
    output (NFR-3). The new key is never present for non-opting consumers.
  - **Semantics**: a non-empty `group.instance.id` makes the member a **static** group member — on a clean
    restart within `session.timeout.ms` Kafka does **not** trigger a rebalance (KIP-345). Combined with
    the existing cooperative-sticky assignor, this removes both the stop-the-world churn *and* the
    transient-restart churn.
- **Hard requirement for the value**: it must be **unique per process within a group** and **stable across
  restarts** of that process. Two live members sharing one `group.instance.id` are **fenced**
  (`FencedInstanceIdException`) — exactly the failure FR-8 prevents in dev. The PRD therefore makes id
  derivation env-specific (numbered service in dev; `metadata.name` of a StatefulSet pod in prod).

#### 6.5b Per-service settings (worldview, `services/*/config.py`) — FR-5

Each service adds one setting per **consumer scope** it runs (a scope = one consumer group / one `*_main.py`).
Pattern (NLP example; verified `env_prefix="NLP_PIPELINE_"`, existing `kafka_consumer_group`):
| Setting | Type | Default | Env var | Notes |
|---------|------|---------|---------|-------|
| `kafka_consumer_instance_id` | str | `""` | `NLP_PIPELINE_KAFKA_CONSUMER_INSTANCE_ID` | Article consumer scope |
| `kafka_watchlist_consumer_instance_id` | str | `""` | `..._WATCHLIST_CONSUMER_INSTANCE_ID` | Watchlist scope |
| `kafka_entity_refresh_consumer_instance_id` | str | `""` | `..._ENTITY_REFRESH_CONSUMER_INSTANCE_ID` | Entity-refresh scope |
- **Default empty** everywhere → no behaviour change unless explicitly set. Only multi-replica consumers
  (the article fleet, plus any prod StatefulSet consumer) need a non-empty value in v1.

#### 6.5c Instantiation sites (worldview) — FR-6

Each `ConsumerConfig(...)` call (**38** total — 28 in `*_main.py`, 10 outside, see FR-6) gains
`group_instance_id=settings.kafka_<scope>_consumer_instance_id`. For single-replica consumers this passes
`""` (no-op). Only the article-fleet `_main.py` sites consume a real value in v1. The 8 `if config is None:`
fallback-default sites in `*_consumer.py` (market-data/content-store) and the 2 `alert/main.py` sites either
take the injected config from their `_main.py` (so no edit needed) or stay dynamic (`""`); they do not need
a real instance id in v1.

#### 6.5d StatefulSet chart variant (gitops, `charts/worldview-service`) — FR-9

- **New template** `templates/statefulset.yaml` rendered when `.Values.statefulSet.enabled` (or
  `.Values.kind == "StatefulSet"`); the existing `deployment.yaml` renders otherwise (mutually exclusive,
  guarded by `{{- if }}`).
- **New headless Service** (`clusterIP: None`) required by StatefulSet for stable DNS; existing
  `service.yaml` gains a `{{- if .Values.statefulSet.enabled }}` headless variant or a companion template.
- **Identity injection** in the pod spec env (both variants support it, but it's only *stable* in the
  StatefulSet):
  ```yaml
  env:
    - name: <SVC>_KAFKA_CONSUMER_INSTANCE_ID
      valueFrom:
        fieldRef:
          fieldPath: metadata.name      # e.g. nlp-pipeline-article-consumer-0
  ```
- **HPA**: not applied to StatefulSet consumers in v1 (lag-based scaling is FR-19). `replicas` is set
  explicitly in the prod overlay.

#### 6.5e Prod overlay scheme (gitops) — FR-15

- **Base** `values/<svc>.yaml`: dev-safe defaults (low `replicaCount`, modest `resources`, `statefulSet`
  absent/false).
- **Overlay** `values/<svc>.prod.yaml`: prod overrides only (higher `replicaCount`/`resources`,
  `statefulSet.enabled: true` + headless service for consumer services, instance-id `fieldRef` env).
- **Wiring**: in each divergent `apps/worldview-<svc>.yaml`, `valueFiles` becomes
  `[../../values/<svc>.yaml, ../../values/<svc>.prod.yaml, secrets...]` — Helm merges in order, last wins.
- **Scope (v1, DECIDED OQ-7)**: Kafka (`apps/infra-kafka.yaml` env-diverges by hand — provisioning +
  multi-broker added) and **all 7 consumer-running services** (alert, content-ingestion, content-store,
  knowledge-graph, market-data, nlp-pipeline, portfolio) — each gets `values/<svc>.prod.yaml`. The 3
  non-consumer services (api-gateway, market-ingestion, rag-chat) keep a single values file (FR-16).

#### 6.5f Dev single-source-of-truth (gitops) — FR-14

- `env/dev/<svc>.env` is authoritative; `services/<svc>/configs/docker.env` is generated.
- New `worldview-gitops/scripts/check-dev-env-drift.sh`: for each service, `diff env/dev/<svc>.env`
  against the live `docker.env`; **non-zero exit on any diff**, printing the offending service. Intended
  for the dev pre-flight (and optionally a CI/make target).
- `setup-dev.sh` prepends a banner to each generated file: `# GENERATED from worldview-gitops/env/dev/
  <svc>.env — DO NOT EDIT; run scripts/setup-dev.sh after editing the gitops source.`

### 6.6 DEV vs PROD configuration matrix (the core deliverable)

| Concern | DEV (single host) | PROD (k8s scale-out) | Owned by |
|---------|-------------------|----------------------|----------|
| **Partitions** | 1–3 per topic (`create-topics.sh`) | current/higher via Bitnami `provisioning.topics` | dev: worldview script · prod: gitops |
| **Brokers** | 1 (KRaft, do **not** add) | **3** (`broker.replicaCount:3`, RF=3, dedicated `controller.controllerOnly:true`) | gitops |
| **Consumer fan-out** | numbered services, count ≤ dev partitions | StatefulSet `replicas` | dev: compose · prod: gitops overlay |
| **Static membership** | per-replica `*_INSTANCE_ID` in `env/dev` | `metadata.name` via downward API | code (lib) + config (both) |
| **CPU isolation** | `deploy.resources` caps ML, reserves Kafka/PG | k8s `resources` + node roles | dev: compose · prod: gitops |
| **Config source** | `env/dev/<svc>.env` (authoritative) → copied | `values/<svc>.yaml` + `.prod.yaml` overlay | gitops |

### 6.7 Data / Control Flow

- **Dev cold start (after fix)**: `make dev` → `create-topics.sh` creates ≤~40 app partitions →
  numbered consumer services start, each with a distinct stable `group.instance.id` → cooperative-sticky +
  static membership → controller handles a small, non-storming join set; ML containers are CPU-capped so
  Kafka/Postgres keep reserved cycles. No manual steps.
- **Prod deploy (after fix)**: ArgoCD syncs `apps/worldview-<svc>.yaml` → chart with
  `[values/<svc>.yaml, values/<svc>.prod.yaml, secrets]` → StatefulSet renders `name-0..N` consumer pods,
  each injecting `metadata.name` as its instance id → static membership across restarts. Bitnami Kafka
  app runs **3 brokers + a dedicated controller** and provisions topics declaratively with prod partition
  counts at **RF=3** (net-new topics; pre-existing RF=1 topics need the RF-migration runbook — §9 / Wave 5).
- **Config edit (after fix)**: developer edits `env/dev/<svc>.env` in gitops → `setup-dev.sh` regenerates
  `docker.env` → `check-dev-env-drift.sh` is green. Editing `docker.env` directly → drift check fails loudly.

---

## 7. Architecture Decisions

- **AD-1 — DEV tunes down, PROD scales out (do NOT add brokers in dev).** A second KRaft node on the same
  host doubles replication + controller work on the same CPU. Rejected. Dev gets fewer partitions + caps;
  **prod pulls the Bitnami multi-broker lever now (3 brokers, RF=3, dedicated controller — OQ-3/OQ-4)**.
  This is the central asymmetry the whole PRD enforces, with both sides now taken explicitly.
- **AD-2 — DEV static membership via explicit numbered services, not `deploy.replicas`.** `deploy.replicas:3`
  hands all replicas identical env → identical `group.instance.id` → `FencedInstanceIdException`. Two options:
  (A) explicit `…-consumer-0/1/2` services each with a distinct `*_INSTANCE_ID`; (B) derive the id from the
  per-replica container hostname (Compose appends `-1/-2/-3`). **Chosen: A** — fully explicit, no hostname
  parsing, trivially readable in compose, and it also lets FR-11 cap the count. B is fragile (hostname format
  is a Compose implementation detail). Recorded as the rejected alternative.
- **AD-3 — PROD static membership requires StatefulSet, not Deployment.** A Deployment's pod name is random
  and changes on restart, so a downward-API `metadata.name` instance id is not *stable* → static membership
  buys nothing. StatefulSet gives `name-0..N` stable across restarts. Hence the chart needs a StatefulSet
  variant (FR-9), not just a values tweak. API/stateless services stay Deployments.
- **AD-4 — Keep the dev copy mechanism + add a drift check; do NOT symlink.** A symlink from `docker.env` to
  `env/dev/<svc>.env` couples the two repo checkout paths and breaks on Windows/CI clones. Rejected for v1.
  The copy + loud drift check (FR-14) keeps the existing, working flow while killing silent drift. FR-17
  (direct `env_file` path) is the eventual cleaner answer, deferred.
- **AD-5 — Prod overlay = base + `.prod.yaml`, not a full env-tree templating engine.** Helm `valueFiles`
  last-wins merge is already how ArgoCD composes values + secrets here; adding one overlay file per divergent
  service is the smallest change that resolves GAP-2. A Kustomize/`environments/` tree was rejected as
  over-engineering for a two-env (dev/prod, plus the existing thin `eval`) platform.
- **AD-6 — `group.instance.id` is purely additive on top of cooperative-sticky.** Because the assignor is
  already cooperative-sticky (shipped), there is **no assignor migration risk**. Adding static membership is
  the lowest-risk lever available and is default-off.

### 7.1 Architecture Compliance Gate (RULES.md)

| Rule | Applies? | Decision | Compliant? |
|------|----------|----------|------------|
| R1 small focused diffs | yes | Split into code (lib/config/sites), dev-infra, gitops-chart, gitops-values waves | PASS |
| R4 tests w/ every change | yes | `to_dict()` unit tests (id present/absent), topic-parity test, drift-check test | PASS |
| R5 Avro forward-compat | no | No schema/event change; partition count is not a schema property | N/A |
| R8 no dual writes | no | No DB+Kafka write path changes | N/A |
| R10 UUIDv7 | no | No IDs generated | N/A |
| R11 UTC | no | No timestamps | N/A |
| R13 use shared libs | yes | Change lands *in* `libs/messaging`; all consumers use it | PASS |
| R14 frontend→S9 only | no | No frontend/API change | N/A |
| R24 intelligence_db DDL | no | No migration | N/A |
| R25/R27 API isolation/read UoW | no | No API/use-case change | N/A |
| R8/secrets in gitops | yes | No `secrets/*.yaml` touched; instance id via downward API | PASS |

No FAIL rows.

---

## 8. Security Analysis

- **Threat: instance-id collision / spoofing.** A duplicated `group.instance.id` fences the legitimate
  member. Mitigated by deriving the id from a uniqueness-guaranteed source (numbered service in dev,
  StatefulSet ordinal in prod). No user-supplied input feeds the id.
- **Threat: secret leakage via new config.** None — all new knobs are non-sensitive (instance ids, partition
  counts, resource caps). No change to SOPS `secrets/*.yaml` (NFR-4). Downward-API `fieldRef` exposes only
  the pod name, already non-secret.
- **Threat: resource-limit DoS in dev.** Caps are protective (prevent ML from starving Kafka/PG); too-low a
  cap could OOM-kill ML — mitigated by sizing reservations from observed `docker stats` and keeping ML
  limits generous-but-bounded.
- **Multi-tenant isolation**: unaffected (no data-path change).
- **PLAINTEXT listeners** (existing in `infra-kafka.yaml`) are unchanged and out of scope.

---

## 9. Failure Modes

| Failure | Cause | Behaviour | Recovery / Mitigation |
|---------|-------|-----------|------------------------|
| **Cannot reduce partitions on existing dev topic** | Kafka forbids decreasing partitions | `create-topics.sh` uses `--if-not-exists`; an *existing* topic keeps its old (high) count | Dev fix applies on a fresh KRaft volume (`make dev` recreate). Document: to apply on a live dev cluster, delete the topic first or recreate the volume. |
| **Duplicate `group.instance.id`** | Two live members share an id (mis-set env / copy-paste) | `FencedInstanceIdException`, one member can't join | Distinct ids per replica (numbered service / StatefulSet ordinal); a startup log line records the id |
| **Stale static member blocks rebalance** | A static member crashes hard; Kafka waits `session.timeout.ms` before reassigning | Brief partition unavailability (≤60 s, current session timeout) | Acceptable; `session.timeout.ms=60s` already tuned. Operator can `kafka-consumer-groups --delete` the stuck instance id |
| **Provisioning job fails in prod** | Bitnami provisioning hook errors (RF > broker count) | Topic not created; ArgoCD app degraded | RF=3 requires `broker.replicaCount: 3` (now set, OQ-3) so RF ≤ broker count holds; provisioning is idempotent; re-sync after fixing values |
| **Existing prod topics stay RF=1 after the RF=3 flip** | Helm/provisioning cannot raise RF on an already-existing topic; only net-new topics get RF=3 | Old topics remain single-replica (no HA) despite the values move | **Operator runbook (NOT executed here)**: either `kafka-reassign-partitions` to add replicas to each existing topic, or stand up a fresh cluster and mirror. Documented in Wave 5 note; prod cluster unreachable from this work. |
| **ML container OOM under new cap** | Memory limit too low for model load | Container killed/restart-loops | Size memory limit ≥ observed model RSS; reservation < limit |
| **Drift check false-positive** | `setup-dev.sh` adds a banner the source lacks | `diff` flags every file | Drift check normalises/ignores the GENERATED banner line |
| **StatefulSet rollout stuck** | Headless Service missing / PVC pending | Pods `Pending` | Headless Service rendered with the variant; consumers are stateless (no PVC needed) — set `volumeClaimTemplates: []` |

Cross-ref `docs/BUG_PATTERNS.md`: this incident becomes a new BP (single-node KRaft partition+rebalance+CPU
overload; "all-green-then-flood" class).

---

## 10. Scalability & Performance

- **Dev**: dropping 212→≤~40 app partitions cuts controller metadata load ~5×; static membership removes the
  cold-start churn; CPU reservations guarantee Kafka/PG cycles. Target: deterministic single-host bring-up
  (NFR-1/2).
- **Prod**: partition counts stay sized for parallelism; StatefulSet consumers scale by `replicas` with
  stable identity; **brokers move to 3 (`broker.replicaCount:3`, RF=3) with a dedicated controller
  (`controller.controllerOnly:true`)** — partitions/offsets now distribute across the quorum. Bitnami
  `offsets.topic.num.partitions` + `offsets.topic.replication.factor=3` set explicitly so the multi-broker
  cluster replicates the offsets topic correctly.
- **Throughput note**: the dev article fleet shrinks (FR-11) but so do dev partitions (FR-1), preserving the
  1:1 consumer:partition assignment that keeps cooperative-sticky efficient. Dev is a functional environment,
  not a throughput benchmark.

---

## 11. Test Strategy

### Unit Tests (worldview)
| Test | What it verifies | Priority |
|------|------------------|----------|
| `test_consumer_config_to_dict_omits_instance_id_when_empty` | `group.instance.id` absent when field `""` (byte-identical to today) | HIGH |
| `test_consumer_config_to_dict_emits_instance_id_when_set` | key present with exact value when non-empty | HIGH |
| `test_consumer_config_instance_id_default_is_empty` | default keeps opt-in semantics | HIGH |
| `test_<svc>_settings_kafka_instance_id_defaults_empty` (per service) | new settings default `""` | HIGH |
| `test_article_consumer_main_passes_instance_id` | `*_main` wires setting → `ConsumerConfig` | MEDIUM |
| `test_topic_set_parity_dev_vs_prod` | dev `create-topics.sh` names == prod provisioning names (FR-3) | HIGH |

### Integration / Infra Tests
| Test | Infra | What it verifies |
|------|-------|------------------|
| `test_create_topics_partition_counts` | parse `create-topics.sh` | every app topic ≤ 3 partitions in dev |
| `test_compose_resources_present` | parse `docker-compose.yml` | `gliner-server`/`ollama`/`kafka`/`postgres` have `deploy.resources` |
| `test_compose_numbered_consumers_have_distinct_instance_ids` | parse compose | each `…-consumer-N` sets a unique `*_INSTANCE_ID` |
| `helm template` lint (gitops CI) | chart | StatefulSet variant renders headless Service + `metadata.name` fieldRef env |
| `check-dev-env-drift.sh` self-test | gitops | passes when in sync, exits non-zero on injected drift (ignoring banner) |

### Manual / E2E
- `make dev` cold start on a laptop → assert zero controller overload log lines + no manual steps (NFR-1).
- `docker stats` during `make seed` → Kafka/PG retain reserved CPU under ML load (NFR-2).

R19: no test deleted/skipped/weakened. Existing `ConsumerConfig.to_dict()` tests must stay green unchanged.

---

## 12. Migration & Rollout

1. **Wave order** (see §15): code (lib → settings → sites) first so the field exists; then dev infra; then
   gitops chart; then gitops values/overlays; then docs.
2. **Backward compatibility**: every code change is default-empty/no-op; merging waves 1–2 of the code change
   alone does not alter any running consumer until a `*_INSTANCE_ID` is actually set.
3. **Dev application**: requires a fresh KRaft volume to realise the partition reduction (existing topics
   can't shrink). Document in `make dev` notes.
4. **Prod application**: ArgoCD picks up the chart + overlay changes on sync; provisioning is idempotent; the
   StatefulSet migration for consumers is a delete-Deployment/create-StatefulSet transition (brief consumer
   gap, acceptable for batch NLP consumers).
5. **No DB migration, no schema migration, no API version bump.**

---

## 13. Observability

- Consumer startup logs the resolved `group.instance.id` (or "dynamic membership" when empty) via structlog.
- Existing Kafka consumer metrics (`<service>_kafka_messages_consumed_total`, lag) unchanged; rebalance count
  should drop to ~0 in dev — watch via kafka-ui / Grafana.
- Add a dashboard note / alert idea (deferred to v2): controller event-queue depth + `REQUEST_TIMED_OUT`
  rate as the canonical "single-node overload" signal.
- Drift check is observable as a make/CI step exit code.

---

## 14. Decisions (formerly Open Questions — all RESOLVED 2026-06-16)

All 8 prior open questions are now firm decisions. Implementers MUST follow the **Decision** column;
the "Rationale" column records why.

| # | Question | **Decision (firm)** | Rationale |
|---|----------|---------------------|-----------|
| **OQ-1** | Exact dev per-topic partition counts (1 vs 2 vs 3 for the article/enriched/signal pipeline)? | **3** for the four pipeline topics `content.article.raw.v1`, `content.article.stored.v1`, `nlp.article.enriched.v1`, `nlp.signal.detected.v1`; **1** for every other app topic (DLQs match their primary where the plan says so). | These four carry the genuinely-parallel pipeline; everything else is low-volume on a single host. Total stays ≤ ~40 app partitions. |
| **OQ-2** | Dev numbered-consumer count for the article fleet (was 3)? | **2** — explicit numbered services `article-consumer-0` and `article-consumer-1`. | Matches a 3-partition article topic with headroom while halving cold-start join load; reduce to 1 on very constrained laptops. |
| **OQ-3** | Flip prod Kafka to multi-broker (`broker.replicaCount: 3`) now? | **YES — flip now. `broker.replicaCount: 3`, `replicationFactor: 3`** in `apps/infra-kafka.yaml` (Wave 5). | User choice — pull the prod scale-out lever now; HA + parallelism for prod. RF-migration of pre-existing topics is a runbook (see caveat below), not executed here. |
| **OQ-4** | Split prod KRaft controller from broker (dedicated controller) when scaling brokers? | **YES — `controller.controllerOnly: true`** (dedicated controller, split from the 3 brokers) in `apps/infra-kafka.yaml` (Wave 5). | Follows OQ-3 — with brokers at 3, a dedicated controller isolates quorum work from broker load. |
| **OQ-5** | Dev single-source-of-truth: keep copy + drift check, or move to direct `env_file` path (FR-17)? | **COPY `gitops/env/dev/*.env → services/<svc>/configs/docker.env` (generated) + a CI drift check.** Repos stay decoupled. | User choice — keeps the two repos independent; AD-4. FR-17 (direct `env_file`) remains a v2 option. |
| **OQ-6** | Reduce dev `offsets.topic.num.partitions` (50 → e.g. 12)? | **DEFER — do not change yet** (FR-20). | Validate it doesn't perturb single-node KRaft bootstrap first; the app-partition cut already resolves the incident. The only item left deferred. |
| **OQ-7** | Which services get a prod overlay in v1? | **ALL 7 consumer-running services** (alert, content-ingestion, content-store, knowledge-graph, market-data, nlp-pipeline, portfolio) — each gets `values/<svc>.prod.yaml` — plus Kafka. | User choice — every consumer service diverges prod↔dev (resources/identity), so all get the overlay now. The 3 non-consumer services stay single-file (FR-16). |
| **OQ-8** | StatefulSet consumers — do they need PVCs? | **NO — render `volumeClaimTemplates: []`.** StatefulSet is used purely for stable identity, not storage. | Consumers are stateless; identity-only StatefulSet. |

**RF-MIGRATION CAVEAT (Wave 5)**: existing prod topics are RF=1, and Helm/Bitnami provisioning **cannot raise
the replication factor of an already-existing topic** — the RF=3 values apply cleanly only to net-new topics
or a fresh cluster. To bring existing topics to RF=3 an operator must run `kafka-reassign-partitions` (add
replicas per topic-partition) or stand up a fresh cluster and mirror. **This runbook is DOCUMENTED, not
executed** — the prod cluster is not reachable from this work. See §9 ("Existing prod topics stay RF=1") and
Wave 5 (T-B-5-01 note).

No BLOCKING questions remain; only OQ-6 stays deferred by decision.

---

## 15. Estimation & Proposed Waves

Two repos, code/config split. Suggested waves (for `/plan`):

- **Wave 1 — Library (worldview, CODE)**: `ConsumerConfig.group_instance_id` + conditional `to_dict()` +
  unit tests + `docs/libs/messaging.md`. (Smallest, unblocks everything.)
- **Wave 2 — Service settings + instantiation (worldview, CODE)**: 7 consumer-service `config.py` settings +
  38 `ConsumerConfig(...)` sites (28 `_main.py` + 10 outside; fallback-default sites optional) pass-through,
  all default-empty + per-service tests.
- **Wave 3 — DEV infra (worldview)**: `create-topics.sh` partition cuts (FIX-1 dev); `docker-compose.yml`
  `deploy.resources` for gliner/ollama/kafka/postgres (FIX-3 dev); replace article `deploy.replicas:3` with
  numbered services + `*_INSTANCE_ID` (FIX-2 dev); infra parse-tests.
- **Wave 4 — GitOps chart (worldview-gitops)**: StatefulSet variant + headless Service template + `helm
  template` lint (FR-9). Dependency for Wave 5 prod consumers.
- **Wave 5 — GitOps values/overlays + provisioning + multi-broker (worldview-gitops)**: `infra-kafka.yaml`
  provisioning (RF=3) + **`broker.replicaCount:3` + `replicationFactor:3` + `controller.controllerOnly:true`**
  + broker `extraConfig` (FIX-1 prod + FR-18); base+`.prod.yaml` overlays for Kafka + **all 7 consumer
  services** with `statefulSet.enabled` + instance-id `fieldRef` + right-sized resources (FIX-2/3 prod +
  GAP-2); wire `valueFiles` on all 7 `apps/worldview-<svc>.yaml`; **document the RF-migration runbook caveat**.
- **Wave 6 — Dev single-source-of-truth + docs (worldview-gitops)**: `check-dev-env-drift.sh`,
  `setup-dev.sh` banner, `env/dev/<svc>.env` instance-id knobs (GAP-1); code/config-split + overlay-model
  docs; `docs/BUG_PATTERNS.md` new BP; `docs/plans/TRACKING.md` row.

Rough effort: ~4–6 working days. Risk: LOW (additive, default-off code; declarative config; no schema/DB/API
change). The only behavioural prod transition is Deployment→StatefulSet for consumers (Wave 4/5), gated and
revertible.

---

## Compounding Check
- **New BP** (to add during implementation): single-node KRaft "partition-count × simultaneous-rebalance ×
  CPU-starvation" controller-overload pattern, with the dev-tunes-down / prod-scales-out resolution and the
  `FencedInstanceIdException` static-membership pitfall.
- **Docs to update**: `docs/libs/messaging.md` (`group_instance_id`), `docs/services/nlp-pipeline.md`
  (numbered consumers), gitops `docs/` (code/config split + overlay model), `docs/plans/TRACKING.md`.
