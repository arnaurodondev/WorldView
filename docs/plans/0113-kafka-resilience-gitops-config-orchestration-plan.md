---
id: PLAN-0113
title: Kafka Resilience (DEV tuning / PROD scale-out) + GitOps Config-Orchestration Model
prd: PRD-0113
status: draft
created: 2026-06-16
updated: 2026-06-16
branch: feat/frontend-enhancement-sprint
repos: [worldview, worldview-gitops]
---

# PLAN-0113 — Kafka Resilience + GitOps Config-Orchestration Model

## Overview

PRD: [PRD-0113](../specs/0113-kafka-resilience-gitops-config-orchestration.md)

**Goal.** Make local-dev Kafka bring-up deterministic (tune *down*: fewer partitions,
static consumer membership, CPU isolation) while keeping the prod posture correct (scale
*out*: declarative topic provisioning, StatefulSet-backed consumers with stable identity,
base+overlay values). Resolve the two structural gitops gaps the incident exposed
(GAP-1 dev config split-source-of-truth; GAP-2 no prod overlay).

**Two repos, code/config split (FR-13).** `worldview` owns the FIX-2 *code*
(`group_instance_id` + plumbing) plus dev infra (`create-topics.sh`, `docker-compose.yml`).
`worldview-gitops` (a **separate git repo** at
`/Users/arnaurodon/Projects/University/final_thesis/worldview-gitops`, SOPS-encrypted
secrets — never edit `secrets/*.yaml`) owns all *config*: prod topic provisioning, the
StatefulSet chart variant, base+`.prod.yaml` overlays, instance-id injection, and the dev
single-source-of-truth machinery.

**No schema / DB / API change.** R5 (Avro forward-compat), R8 (dual-write/outbox), R10
(UUIDv7), R11 (UTC), R14 (frontend→S9), R24 (intelligence_db DDL), R25/R27 (API isolation /
read UoW) are **all N/A** — verified against PRD §6.2–6.4 and §7.1. The only engaged rules
are R1 (small diffs), R4 (tests), R13 (use shared libs), R15 (docs), R19 (never weaken
tests). Every code change is **additive, default-empty/no-op** (NFR-3 byte-identical config
for non-opting consumers).

### Services / scopes affected (worldview)

**7 consumer-running services** (verified this session — these are the ONLY services that instantiate
`ConsumerConfig`; `market-ingestion`, `api-gateway`, `rag-chat` have **zero** `ConsumerConfig` sites and are
NOT touched by FIX-2):

| Service | env_prefix (verified) | Consumer scopes / sites |
|---------|----------------------|-------------------------|
| nlp-pipeline | `NLP_PIPELINE_` | article, watchlist, entity_refresh, document_deletion (4 `_main.py` sites) |
| knowledge-graph | `KNOWLEDGE_GRAPH_` (verify exact) | 13 `_main.py` consumer sites (enriched/dataset/instrument/temporal/etc.) |
| market-data | `MARKET_DATA_` (verify exact) | 12 sites: 6 `_main.py` + 6 `*_consumer.py` `if config is None:` fallback defaults |
| content-store | `CONTENT_STORE_` (verify exact) | 3 sites: 1 `_main.py` + 2 `*_consumer.py` fallback defaults |
| alert | `ALERT_` | 3 sites: 2 `*_main.py` + `services/alert/main.py` (1 site, NOT under `consumers/`) |
| content-ingestion | `CONTENT_INGESTION_` | 1 `_main.py` site (document_ready) |
| portfolio | `PORTFOLIO_` | 1 `_main.py` site (instrument) |

> **38** `ConsumerConfig(...)` non-test call sites exist (verified
> `git grep -n "ConsumerConfig(" services --include="*.py" | grep -v test | wc -l` = 38). **28** are in
> `*/consumers/*_main.py`; the other **10** are outside `_main.py`: `services/alert/main.py` (2) and 8
> `*_consumer.py` files where `ConsumerConfig(...)` is a `if config is None:` fallback default (market-data ×6,
> content-store ×2). The fallback-default sites take their real config from the matching `_main.py`, so only
> the `_main.py` sites need the instance-id pass-through; wiring the fallbacks is optional in v1 (they stay
> empty/dynamic). 29 `*/consumers/*_main.py` files exist but one (content-store `article_consumer_main.py`)
> shares a class with its `_consumer.py`. **Wave 2 begins with a mechanical enumeration pass**
> (`git grep -n "ConsumerConfig("`) to produce the authoritative scope→setting→site table before any edit.

## Dependency Graph

```
W1 (DEV quick wins: partition cut + compose CPU caps)        ── zero prod-risk, independent
W2 (FIX-2 CODE: lib field + service settings + wiring)       ── depends on nothing; lib first
        │
        ▼
W3 (DEV static membership: numbered consumer services)       ── depends on W2 (needs the settings)
        │
W4 (GitOps chart: StatefulSet variant + headless Service)    ── worldview-gitops; independent of W1-W3 code
        │
        ▼
W5 (GitOps values/overlays ×7 + provisioning + multi-broker) ── depends on W4 (uses statefulSet.enabled)
        │
W6 (Dev single-source-of-truth + docs + BP + TRACKING)       ── depends on W2/W3 (env knobs) + W5 (overlay docs)
```

**Critical path:** W2 → W3 → (W4 → W5) → W6. W1 is shippable immediately and in parallel
with everything. W4 (gitops chart) is independent of the worldview code waves and can run in
parallel with W1–W3.

**Recommended execution order:** W1 (or W1 ∥ W2) → W2 → W3 → W4 → W5 → W6.

## Tracking Table

| Wave | Title | Repo | Status | Tasks |
|------|-------|------|--------|-------|
| W1 | DEV quick wins — partition cut + compose CPU caps | worldview | done | 4 |
| W2 | FIX-2 CODE — `group_instance_id` lib + service settings + wiring | worldview | pending | 5 |
| W3 | DEV static membership — numbered consumer services | worldview | pending | 4 |
| W4 | GitOps chart — StatefulSet variant + headless Service | worldview-gitops | pending | 4 |
| W5 | GitOps values/overlays (×7) + Bitnami provisioning + multi-broker | worldview-gitops | pending | 6 |
| W6 | Dev single-source-of-truth + docs + BP | both | pending | 5 |

## Codebase State Verification (read this session)

| PRD Reference | Type | Repo/Loc | Actual Current State | PRD Expected | Delta |
|---------------|------|----------|----------------------|--------------|-------|
| `ConsumerConfig` | dataclass | `libs/messaging/src/messaging/kafka/consumer/base.py:221` | `partition_assignment_strategy="cooperative-sticky"` (l.293); `to_dict()` (l.318) **`return`s `apply_base_rdkafka_config({...})` directly** (single expr — must refactor to local var to insert the conditional key); `enable_persistent_retry: bool = False` (l.316) default-off precedent; **no** `group_instance_id` | add `group_instance_id: str = ""` + refactor `to_dict()` return → local var + conditional emit | lib field + to_dict |
| `create-topics.sh` `TOPICS` | shell array | `infra/kafka/init/create-topics.sh:34` | 22 app topics `name:partitions:rf` (3..24) + compacted `entity.dirtied.v1:24`; sums to 212 app | dev counts 1–3 (≤~40 app) | edit array values |
| `docker-compose.yml` ML resources | compose | `infra/compose/docker-compose.yml` | `deploy.resources` commented out (~l.1185/1261); services use `env_file: configs/docker.env` | add limits/reservations to gliner/ollama/kafka/postgres | add deploy blocks |
| `nlp-pipeline-article-consumer` | compose service | `infra/compose/docker-compose.yml` | single service `deploy.replicas:3` | replace with numbered `-0/-1/-2` (count per OQ-2 = 2) | restructure |
| `ConsumerConfig(...)` sites | code | 28 in `services/*/.../consumers/*_main.py` + 10 outside (`alert/main.py` ×2, 8 `*_consumer.py` fallback defaults) | `ConsumerConfig(...)` w/o `group_instance_id` | pass `group_instance_id=settings.<...>` (fallback-default sites optional) | **38** sites (7 services only) |
| `apps/infra-kafka.yaml` | gitops | `worldview-gitops/apps/infra-kafka.yaml` | Bitnami 32.4.3, `broker.replicaCount:1` (verify exact key — chart 32.x uses `broker.replicaCount`/`controller.replicaCount` under KRaft), `controller.replicaCount:1`, **no** `provisioning` block (auto-create); `extraConfig` **already exists** (retention/message.max.bytes) | flip `broker.replicaCount:3` + `replicationFactor:3` + `controller.controllerOnly:true` (OQ-3/OQ-4); add `provisioning.enabled`+`topics[]` (RF=3); **append** `num.partitions`/`offsets.topic.num.partitions`/`default.replication.factor=3`/`offsets.topic.replication.factor=3`/`transaction.state.log.replication.factor=3` to existing `extraConfig` | multi-broker flip + net-new provisioning block + extraConfig append |
| `charts/worldview-service/templates/` | gitops | `worldview-gitops/charts/worldview-service/templates/` | `deployment.yaml` (inlines container/env/probes — **no** shared pod-spec helper), `service.yaml`, `hpa.yaml`, `serviceaccount.yaml`, `_helpers.tpl` (only name/labels/SA defines) — **no** StatefulSet | extract pod-spec `define` into `_helpers.tpl` first, then add `statefulset.yaml` + headless Service variant | net-new template + helper extraction |
| `apps/worldview-<svc>.yaml` (×7 consumer services) | gitops | `worldview-gitops/apps/worldview-{alert,content-ingestion,content-store,knowledge-graph,market-data,nlp-pipeline,portfolio}.yaml` | each `valueFiles: [values/<svc>.yaml, secrets...]` (no prod overlay); all 7 `values/<svc>.yaml` + `apps/worldview-<svc>.yaml` confirmed present this session | add `values/<svc>.prod.yaml` to each (×7, OQ-7) | wire overlay on all 7 |
| `scripts/setup-dev.sh` | gitops | `worldview-gitops/scripts/setup-dev.sh` | copies `env/dev/<svc>.env → ../worldview/services/<svc>/configs/docker.env`; no banner/drift check | add banner + `check-dev-env-drift.sh` | net-new script + banner |

## Name Verification (BP-405 guard)

| Name | Kind | Status |
|------|------|--------|
| `ConsumerConfig` | class | EXISTS (`base.py:219`) |
| `to_dict` | method | EXISTS (`base.py:317`) |
| `apply_base_rdkafka_config` | function | EXISTS (called in `to_dict`) |
| `enable_persistent_retry` | field | EXISTS (default-off precedent) |
| `group_instance_id` | field | **NEW — created in W2** |
| `kafka_consumer_instance_id` (+ scope variants) | pydantic settings | **NEW — created in W2** |
| `create-topics.sh` `TOPICS` array | shell | EXISTS |
| `check-dev-env-drift.sh` | gitops script | **NEW — created in W6** |
| `charts/worldview-service/templates/statefulset.yaml` | helm template | **NEW — created in W4** |
| `values/<svc>.prod.yaml` (×7 consumer services) | gitops values | **NEW — created in W5** (alert, content-ingestion, content-store, knowledge-graph, market-data, nlp-pipeline, portfolio) |
| `provisioning.topics` | Bitnami chart key | EXISTS (Bitnami 32.4.3 chart) — block is NEW in our `infra-kafka.yaml` |
| `broker.replicaCount` / `controller.controllerOnly` | Bitnami chart keys | EXISTS (Bitnami 32.4.3 KRaft chart) — flipped to 3 / true in W5 (verify exact key names against the chart at implement time) |

---

## Sub-Plan A — worldview (code + dev infra)

### Wave 1: DEV quick wins — partition cut + compose CPU caps

**Goal**: Land the two zero-prod-risk dev fixes (FIX-1 dev partitions, FIX-3 dev CPU isolation) that need no code change, with parse-tests to lock them in.
**Depends on**: none
**Estimated effort**: 45–75 min
**Architecture layer**: infrastructure (dev only)

#### Tasks

#### T-A-1-01: Reduce dev partition counts in create-topics.sh
**Type**: config
**depends_on**: none
**blocks**: T-A-1-04
**Target files**: `infra/kafka/init/create-topics.sh`
**PRD reference**: §3.1 FR-1, §14 OQ-1

**What to build**: Rewrite the `TOPICS` array partition counts so the single KRaft node carries ≤~40 app partitions (from 212). Per OQ-1 default: **3** for the genuinely-parallel pipeline topics (`content.article.raw.v1`, `content.article.stored.v1`, `nlp.article.enriched.v1`, `nlp.signal.detected.v1`); **1** for every other app topic. Drop the compacted `entity.dirtied.v1` from 24 to 1 (compaction key correctness is unaffected by partition count for a single-node dev). Keep `--if-not-exists` semantics (NFR-5).

**Logic & Behavior**:
- Edit only the `:partitions:` middle field of each `name:partitions:rf` entry; do NOT rename topics or change RF (stays 1 in dev).
- Final per-topic table (dev): article/stored/enriched/signal = 3; all others (portfolio.*, market.*, graph.*, intelligence.*, relation.*, entity.*, alert.*, *.dead-letter.*, market.prediction.v1) = 1; `entity.dirtied.v1` (compacted) = 1.
- Add a header comment block citing PRD-0113 FR-1 + OQ-1 and the 212→≤~40 rationale (single-host controller-load).

**Tests to write**: see T-A-1-04 (parse test).

**Acceptance criteria**:
- [ ] Sum of app-topic partitions (including compacted) ≤ 40
- [ ] The 4 pipeline topics = 3 partitions; all others = 1
- [ ] No topic name added/removed/renamed; RF unchanged (1)
- [ ] `--if-not-exists` preserved on every `--create`

#### T-A-1-02: Add deploy.resources CPU/memory caps to docker-compose.yml
**Type**: config
**depends_on**: none
**blocks**: T-A-1-04
**Target files**: `infra/compose/docker-compose.yml`
**PRD reference**: §3.1 FR-10, §3.3 NFR-2, §8

**What to build**: Add `deploy.resources.limits` (CPU+mem) to `gliner-server` and `ollama` (cap them) and `deploy.resources.reservations` (CPU+mem) to `kafka` and `postgres` (guarantee them) so ML inference cannot starve the event backbone. Uncomment/replace the existing commented blocks (~l.1185/1261).

**Logic & Behavior**:
- `gliner-server`, `ollama`: `limits` cap CPU (e.g. `cpus: "2.0"` each — size from observed `docker stats`, leave generous mem `limits` ≥ model RSS to avoid OOM per §9 "ML container OOM").
- `kafka`, `postgres`: `reservations` guarantee CPU (e.g. `cpus: "1.0"` each) + reasonable mem reservation.
- `reservation < limit` invariant for any service that has both.
- Add an inline comment on each block: "PRD-0113 FR-10 — protect Kafka/PG from ML CPU starvation."
- Note: Compose `deploy.resources` requires Swarm-mode semantics under classic `docker compose`; if the repo uses `docker compose` (Compose v2 honours `deploy.resources.limits`), confirm at implement time. If limits are not honoured by the local runtime, fall back to top-level `cpus:`/`mem_limit:` (document choice in the commit).

**Tests to write**: see T-A-1-03.

**Acceptance criteria**:
- [ ] `gliner-server` + `ollama` have `limits` (cpus + memory)
- [ ] `kafka` + `postgres` have `reservations` (cpus + memory)
- [ ] No `reservation > limit` anywhere
- [ ] `docker compose config` parses without error

#### T-A-1-03: Parse-test for compose resources
**Type**: test
**depends_on**: T-A-1-02
**blocks**: none
**Target files**: a new infra test under the repo's existing infra-test location (e.g. `tests/infra/test_compose_resources.py` — verify the conventional path at implement time; mirror any existing compose-parsing test)
**PRD reference**: §11 Integration/Infra Tests

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_compose_resources_present | `gliner-server`/`ollama`/`kafka`/`postgres` all have a `deploy.resources` (or fallback) block | infra |
| test_compose_reservations_le_limits | for any service with both, reservation ≤ limit | infra |
- Parse `infra/compose/docker-compose.yml` with `yaml.safe_load`.
- Minimum test count: 2.

**Acceptance criteria**:
- [ ] Both tests pass against the edited compose file
- [ ] Tests fail if a resource block is removed (assert presence, not just absence-of-error)

#### T-A-1-04: Parse-test for dev partition counts
**Type**: test
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**: a new infra test (e.g. `tests/infra/test_create_topics.py`)
**PRD reference**: §11, §3.1 FR-1

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_create_topics_partition_counts | every app topic ≤ 3 partitions in dev | infra |
| test_create_topics_total_le_40 | sum of declared app partitions ≤ 40 | infra |
- Parse the `TOPICS=( ... )` array and the compacted-topic block out of `create-topics.sh` with a regex.
- Minimum test count: 2.

**Acceptance criteria**:
- [ ] Both tests pass
- [ ] Test enumerates the same topic set used later in W5 parity test (FR-3)

#### Pre-read
- `infra/kafka/init/create-topics.sh` (full)
- `infra/compose/docker-compose.yml` (gliner-server, ollama, kafka, postgres service blocks + the commented `deploy.resources`)
- any existing compose/topics parse test (search `tests/` for `docker-compose` / `create-topics`)

#### Validation Gate
- [ ] ruff check passes on new test files
- [ ] mypy passes on new test files
- [ ] New infra tests pass — minimum 4 new tests
- [ ] `docker compose config` parses
- [ ] No architecture violations (infra-only, no domain touch)

#### Architecture Compliance
- [ ] R1 small diffs — partition edits + compose edits are separate commits if large
- [ ] R4 tests with every change — parse tests included this wave
- [ ] R11/R10/R12 — N/A (no Python runtime code)
- [ ] R32 — N/A (no Alembic)

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| any existing compose-parse test asserting old partition counts | partition values change | update expected counts to the new dev table |
| dev volumes with existing topics | Kafka cannot shrink partitions on an existing topic (§9) | document: apply on fresh KRaft volume (`make dev` recreate); not a code break |

#### Regression Guardrails
- **BP-001 / Kafka topic config**: changing partition counts only — confirm no consumer assumes a fixed partition count (none do; consumers are partition-agnostic per PRD §6.3).
- **§9 Failure Mode "cannot reduce partitions on existing topic"**: `--if-not-exists` means an existing high-partition topic is NOT shrunk silently; document the fresh-volume requirement in the commit + W6 docs.

---

### Wave 2: FIX-2 CODE — group_instance_id lib + service settings + wiring

**Goal**: Add the static-membership primitive (`group.instance.id`) end-to-end as a purely additive, default-empty, no-op change across the shared lib, the **7 consumer-running** service configs, and the 28 `_main.py` consumer instantiation sites (10 outside-`_main.py` sites optional).
**Depends on**: none (lib task first within the wave)
**Estimated effort**: 90 min
**Architecture layer**: shared library + application config

#### Tasks

#### T-A-2-01: Add group_instance_id field + conditional to_dict emit (libs/messaging)
**Type**: impl
**depends_on**: none
**blocks**: [T-A-2-02, T-A-2-03, T-A-2-04, T-A-2-05]
**Target files**: `libs/messaging/src/messaging/kafka/consumer/base.py`
**PRD reference**: §3.1 FR-4, §6.5a, §3.3 NFR-3

**What to build**: Add `group_instance_id: str = ""` to the `ConsumerConfig` dataclass (placed near `enable_persistent_retry` at l.316, mirroring that default-off precedent). In `to_dict()` (l.318), **refactor the current single-expression `return apply_base_rdkafka_config({...})` into `cfg = apply_base_rdkafka_config({...})` bound to a local**, then conditionally insert `"group.instance.id"` ONLY when the field is non-empty, then `return cfg`. (Verified this session: `to_dict()` currently returns the call directly — there is no local var today.)

**Entities / Components**:
- **Name**: `ConsumerConfig.group_instance_id`
- **Purpose**: opt-in static group membership (KIP-345) on top of the already-shipped cooperative-sticky assignor (no assignor migration — AD-6).
- **Key attributes**: `group_instance_id: str = ""` (dataclass field, default empty).
- **Invariants**: when `== ""`, `to_dict()` output is **byte-identical** to today (NFR-3) — the key is never present. When non-empty, value must be unique-per-process-within-group and stable-across-restarts (callers guarantee this, not the lib).
- **Key methods**: `to_dict()` — append:
  ```python
  cfg = apply_base_rdkafka_config({ ...existing keys... })
  if self.group_instance_id:
      cfg["group.instance.id"] = self.group_instance_id
  return cfg
  ```
- **Depends on**: nothing new.

**Logic & Behavior**:
- Add a docstring/comment block explaining static membership semantics + the `FencedInstanceIdException` risk on duplicate ids (§9).
- Do NOT change any other key or default.

**Tests to write** (in `libs/messaging/tests/unit/`):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_consumer_config_instance_id_default_is_empty | default field value is `""` | unit |
| test_consumer_config_to_dict_omits_instance_id_when_empty | `"group.instance.id"` NOT in dict when empty (byte-identical to today) | unit |
| test_consumer_config_to_dict_emits_instance_id_when_set | key present with exact value when non-empty | unit |
- Minimum test count: 3.
- Edge cases: whitespace-only string is treated as truthy → emitted (document; callers must pass clean ids).

**Downstream test impact**:
- `libs/messaging/tests/unit/test_kafka_config.py` (and any existing `to_dict()` assertion) — must stay green UNCHANGED (NFR-3). If an existing test snapshots the full dict, confirm it still matches when the field is empty. **Do not modify these to accommodate the new key** — they prove byte-identity.

**Acceptance criteria**:
- [ ] Field added with default `""`
- [ ] Key emitted only when non-empty
- [ ] All 3 new tests pass + existing `to_dict()` tests green unchanged

#### T-A-2-02: Enumerate consumer scopes (mechanical pass — produces the authoritative table)
**Type**: docs
**depends_on**: [T-A-2-01]
**blocks**: [T-A-2-03, T-A-2-04]
**Target files**: this plan file (append the table) — no code change
**PRD reference**: §6.1, §6.5b/c

**What to build**: Run `git grep -n "ConsumerConfig("` and `find services -path '*/consumers/*_main.py'` to produce the authoritative map of: service → env_prefix → consumer scope (group) → `*_main.py` file → `config.py` setting name (FR-5 naming `kafka_<scope>_consumer_instance_id`). This removes guesswork from T-A-2-03/04.

**Acceptance criteria**:
- [ ] Every `ConsumerConfig(...)` call site listed with its service + scope
- [ ] Setting name proposed per scope, env-prefixed
- [ ] **38** sites accounted for (28 `_main.py` + 10 outside); verify against `git grep -n "ConsumerConfig(" services --include="*.py" | grep -v test | wc -l` = 38
- [ ] Fallback-default sites (`if config is None:` in `*_consumer.py`) flagged as optional-to-wire

#### T-A-2-03: Add per-service kafka_*_consumer_instance_id settings (7 config.py)
**Type**: impl
**depends_on**: [T-A-2-02]
**blocks**: [T-A-2-04]
**Target files**: `services/*/src/*/config.py` for the **7 consumer-running services only** (alert, content-ingestion, content-store, knowledge-graph, market-data, nlp-pipeline, portfolio) per the W2 enumeration table. **Do NOT touch** market-ingestion / api-gateway / rag-chat — they have no `ConsumerConfig` site.
**PRD reference**: §3.1 FR-5, §6.5b

**What to build**: For each consumer scope a service runs, add one pydantic-settings field `kafka_<scope>_consumer_instance_id: str = ""` (env-prefixed via the service's existing `env_prefix`). NLP example (verify prefix): `kafka_consumer_instance_id`, `kafka_watchlist_consumer_instance_id`, `kafka_entity_refresh_consumer_instance_id`, `kafka_document_deletion_consumer_instance_id`.

**Logic & Behavior**:
- Default `""` everywhere → no behaviour change unless explicitly set (preserves NFR-3 at the service level).
- Follow each service's existing settings style (descriptions, ordering).

**Tests to write** (per service, in its `tests/unit/test_config.py` or equivalent):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_<svc>_settings_kafka_instance_id_defaults_empty | each new setting defaults `""` | unit |
- Minimum: 1 assertion per new setting per service.

**Downstream test impact**:
- Each service's existing `test_config.py` — ensure new fields don't break existing settings-construction tests (defaults make this safe; verify no `extra="forbid"` env collision).

**Acceptance criteria**:
- [ ] One setting per consumer scope per service, default `""`
- [ ] Per-service default test passes
- [ ] No existing config test breaks

#### T-A-2-04: Wire settings into ConsumerConfig(...) call sites (28 _main.py sites; 10 fallback optional)
**Type**: impl
**depends_on**: [T-A-2-03]
**blocks**: [T-A-3-* (W3 dev membership reads these)]
**Target files**: the 28 `ConsumerConfig(...)` sites in `services/*/.../consumers/*_main.py` (required) + optionally the 10 outside-`_main.py` sites (`alert/main.py`, `*_consumer.py` fallback defaults). Across the **7** consumer-running services only.
**PRD reference**: §3.1 FR-6, §6.5c

**What to build**: At each `ConsumerConfig(...)` instantiation, add `group_instance_id=settings.kafka_<scope>_consumer_instance_id`. For single-replica consumers this passes `""` (no-op). Log the resolved id (or "dynamic membership" when empty) via structlog at consumer start (PRD §13).

**Logic & Behavior**:
- Match each site to the correct scope setting using the W2 enumeration table (T-A-2-02).
- Add a one-line structlog `logger.info("consumer membership", group_instance_id=... or "dynamic")` at startup (R12 — structlog only).

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_article_consumer_main_passes_instance_id | the article `*_main` constructs `ConsumerConfig` with `group_instance_id` from settings | unit |
| test_<other_scope>_main_passes_instance_id (≥1 more scope) | wiring for a second scope | unit |
- Minimum test count: 2 (representative; not all 36 need a test, but cover ≥2 distinct services/scopes).

**Acceptance criteria**:
- [ ] Every `ConsumerConfig(...)` site passes a `group_instance_id`
- [ ] Empty-default sites are behaviourally unchanged
- [ ] Startup logs the membership mode via structlog
- [ ] ≥2 wiring tests pass

#### T-A-2-05: Update docs/libs/messaging.md (group_instance_id)
**Type**: docs
**depends_on**: [T-A-2-01]
**blocks**: none
**Target files**: `docs/libs/messaging.md`
**PRD reference**: §3.1 FR-4, R15

**What to build**: Document the new field: semantics (static membership, KIP-345), default-off/byte-identical guarantee, the uniqueness+stability requirement, the `FencedInstanceIdException` pitfall on duplicate ids, and the env-specific derivation (numbered service in dev, StatefulSet `metadata.name` in prod).

**Acceptance criteria**:
- [ ] `group_instance_id` documented with the duplicate-id pitfall
- [ ] Cross-references PRD-0113 + the dev/prod derivation split

#### Pre-read
- `libs/messaging/src/messaging/kafka/consumer/base.py:219-345`
- `libs/messaging/tests/unit/test_kafka_config.py`
- one example `*_main.py` (e.g. `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer_main.py`) + its `config.py`
- `docs/libs/messaging.md`

#### Validation Gate
- [ ] ruff check passes on changed files
- [ ] mypy passes on `libs/messaging` + every changed service package
- [ ] Unit tests pass — minimum 6 new tests (3 lib + ≥1 config + ≥2 wiring)
- [ ] Existing `ConsumerConfig.to_dict()` tests GREEN UNCHANGED (NFR-3)
- [ ] `docs/libs/messaging.md` updated

#### Architecture Compliance
- [ ] R1 small diffs — lib / settings / sites can be separate commits
- [ ] R4 tests with every change — yes
- [ ] R13 use shared libs — change lands IN `libs/messaging`, all consumers use it
- [ ] R12 structlog — startup membership log uses structlog
- [ ] R19 never weaken tests — existing to_dict tests must NOT be edited to accommodate the new key
- [ ] R5/R8/R10/R11/R24/R25/R27 — N/A (no schema/event/DB/API/ID/time/use-case change)

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `libs/messaging/tests/unit/test_kafka_config.py` | IF it snapshots the full `to_dict()` dict | confirm empty-default keeps it identical; DO NOT add the new key to the snapshot (R19) |
| per-service `test_config.py` | new settings fields | add default-empty assertions; ensure no `extra="forbid"` collision |
| consumer `*_main.py` unit tests that construct `ConsumerConfig` mocks | constructor gains a kwarg | additive kwarg with default — existing calls unaffected; verify |

#### Regression Guardrails
- **NFR-3 byte-identity**: the single most important guard — the 30 non-opting consumers must produce an identical rdkafka dict. The omit-when-empty conditional is what enforces it; the lib test proves it.
- **§9 duplicate `group.instance.id` → FencedInstanceIdException**: the lib does not enforce uniqueness; W3 (dev) and W5 (prod) must supply distinct stable ids. Document in T-A-2-05.
- **BP-405 (hallucinated names)**: T-A-2-02 enumeration pass is the guard — every setting name is grepped against the real `config.py` before use.


---

### Wave 3: DEV static membership — numbered consumer services

**Goal**: Give dev consumers stable, distinct `group.instance.id`s by replacing the `deploy.replicas:3` article fleet with explicit numbered services (AD-2), each setting a unique `*_INSTANCE_ID`, capped per OQ-2.
**Depends on**: W2 (the settings + lib field must exist)
**Estimated effort**: 60 min
**Architecture layer**: infrastructure (dev only)

#### Tasks

#### T-A-3-01: Replace article-consumer deploy.replicas:3 with numbered services
**Type**: config
**depends_on**: [T-A-2-04]
**blocks**: [T-A-3-03]
**Target files**: `infra/compose/docker-compose.yml`
**PRD reference**: §3.1 FR-8/FR-11, §7 AD-2, §14 OQ-2

**What to build**: Remove the `deploy.replicas: 3` block from `nlp-pipeline-article-consumer` and replace it with explicit numbered services `nlp-pipeline-article-consumer-0` and `nlp-pipeline-article-consumer-1` (count = 2 per OQ-2; matches the 3-partition article topic with headroom). Each service is identical except for a distinct `NLP_PIPELINE_KAFKA_CONSUMER_INSTANCE_ID` env (e.g. `article-consumer-0`, `article-consumer-1`), set via `environment:` override on top of the shared `env_file`.

**Logic & Behavior**:
- Each numbered service uses the same image/command/env_file as the original; only the `INSTANCE_ID` env differs (set in `environment:` so it overrides the empty `env_file` default).
- Distinct ids prevent `FencedInstanceIdException` (AD-2, §9).
- Keep the count knob obvious (a comment: "OQ-2 default 2; reduce to 1 on constrained laptops; must be ≤ dev article partition count").
- If other dev consumers were also `deploy.replicas>1`, apply the same numbered pattern (verify during T-A-2-02 enumeration; PRD names only the article fleet for v1).

**Tests to write**: see T-A-3-03.

**Acceptance criteria**:
- [ ] No `deploy.replicas` on any static-membership consumer
- [ ] 2 numbered article-consumer services, each with a distinct `*_INSTANCE_ID`
- [ ] All other env identical to the original service
- [ ] `docker compose config` parses

#### T-A-3-02: Set the dev INSTANCE_ID defaults in env (worldview side)
**Type**: config
**depends_on**: [T-A-2-04]
**blocks**: [T-A-3-03]
**Target files**: `services/nlp-pipeline/configs/docker.env` (generated — but the authoritative source `env/dev/nlp-pipeline.env` is edited in gitops W6; here keep the generated artifact consistent so dev works before W6 lands)
**PRD reference**: §3.1 FR-8, §6.6, GAP-1 (full resolution in W6)

**What to build**: Ensure the numbered services' `*_INSTANCE_ID` values come from `environment:` overrides in compose (T-A-3-01), NOT from the shared `docker.env` (which is one value for all). The shared `docker.env` keeps `NLP_PIPELINE_KAFKA_CONSUMER_INSTANCE_ID=` empty (default); per-replica distinctness lives in the numbered service `environment:` blocks. This task documents that split in a compose comment and verifies no stale single value is set in `docker.env`.

**Note**: The authoritative `env/dev/nlp-pipeline.env` instance-id knobs are added in W6 (GAP-1). This task only guarantees the dev stack is internally consistent in the interim.

**Acceptance criteria**:
- [ ] Shared `docker.env` does not set a single article `INSTANCE_ID` (would fence the fleet)
- [ ] Per-replica ids live only in compose `environment:` overrides
- [ ] Comment cross-references W6 for the authoritative source

#### T-A-3-03: Parse-test for distinct instance ids on numbered consumers
**Type**: test
**depends_on**: [T-A-3-01, T-A-3-02]
**blocks**: none
**Target files**: `tests/infra/test_compose_resources.py` (extend) or a new `tests/infra/test_compose_consumers.py`
**PRD reference**: §11

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_compose_numbered_consumers_have_distinct_instance_ids | each `…-consumer-N` sets a unique `*_INSTANCE_ID` | infra |
| test_compose_no_replicas_on_static_consumers | numbered consumers do not use `deploy.replicas` | infra |
- Minimum test count: 2.

**Acceptance criteria**:
- [ ] Both tests pass; fail if two numbered services share an id

#### T-A-3-04: Update docs/services/nlp-pipeline.md (numbered consumers)
**Type**: docs
**depends_on**: [T-A-3-01]
**blocks**: none
**Target files**: `docs/services/nlp-pipeline.md`, `services/nlp-pipeline/.claude-context.md`
**PRD reference**: §3.1 FR-8, R15

**What to build**: Document the dev numbered-consumer model (why not `deploy.replicas`), the `FencedInstanceIdException` rationale, the OQ-2 count knob, and the dev/prod identity split (numbered service vs StatefulSet ordinal).

**Acceptance criteria**:
- [ ] nlp-pipeline service doc + context updated with the numbered-consumer model

#### Pre-read
- `infra/compose/docker-compose.yml` (`nlp-pipeline-*` service blocks)
- the W2 enumeration table (T-A-2-02)
- `docs/services/nlp-pipeline.md`

#### Validation Gate
- [ ] ruff/mypy on new test files
- [ ] Infra tests pass — minimum 2 new tests
- [ ] `docker compose config` parses
- [ ] nlp-pipeline doc + context updated

#### Architecture Compliance
- [ ] R1 small diffs — compose restructure isolated
- [ ] R4 tests with every change — distinct-id parse test
- [ ] R10/R11/R12/R24/R32 — N/A (no Python runtime/Alembic)

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| any compose-parse test counting service instances | service count changes (1 replica-3 → 2 named) | update expected service set |
| docs referencing `nlp-pipeline-article-consumer` (singular) | renamed to `-0/-1` | update doc references |

#### Regression Guardrails
- **§9 duplicate `group.instance.id`**: the distinct-id parse test (T-A-3-03) is the direct guard against the fencing failure mode.
- **OQ-2 count ≤ partition count**: comment + doc note so a future increase past the dev partition count (3) doesn't create idle/fenced members.

---

## Sub-Plan B — worldview-gitops (config) — SEPARATE REPO

> All tasks below modify the **separate git repo** at
> `/Users/arnaurodon/Projects/University/final_thesis/worldview-gitops`. NEVER edit
> `secrets/*.yaml` (SOPS-encrypted, NFR-4). Validation is `helm template` / `helm lint` /
> kubeconform — not pytest. Stay on the worldview branch; do not commit in either repo.

### Wave 4: GitOps chart — StatefulSet variant + headless Service

**Goal**: Add a StatefulSet workload variant to the shared `charts/worldview-service` so multi-replica consumers get stable `name-0/1/2` identities (AD-3, FR-9), gated by values; Deployment stays the default for stateless services.
**Depends on**: none (gitops repo; parallel to W1–W3). Blocks W5.
**Estimated effort**: 75 min
**Architecture layer**: helm chart (gitops)

#### Tasks

#### T-B-4-01: Add statefulset.yaml template (gated)
**Type**: config
**depends_on**: none
**blocks**: [T-B-4-02, T-B-4-04, T-B-5-02]
**Target files**: `worldview-gitops/charts/worldview-service/templates/statefulset.yaml` (NEW), `worldview-gitops/charts/worldview-service/templates/deployment.yaml` (add the mutual-exclusion guard), `worldview-gitops/charts/worldview-service/values.yaml` (add `statefulSet.enabled: false` default)
**PRD reference**: §3.1 FR-9, §6.5d, §7 AD-3

**What to build**: New `statefulset.yaml` rendered only when `.Values.statefulSet.enabled` (default false). Wrap the existing `deployment.yaml` body in `{{- if not .Values.statefulSet.enabled }}` so exactly one workload renders. Set `serviceName:` to the headless service (T-B-4-02), `replicas:` from values, and `volumeClaimTemplates: []` (OQ-8 — consumers are stateless).

**IMPORTANT (verified this session — stale assumption corrected)**: `_helpers.tpl` currently defines **only** `name`/`fullname`/`labels`/`selectorLabels`/`serviceAccountName` — there is **NO** shared pod-spec/container helper. `deployment.yaml` inlines `containers:`/`env:`/probes directly (l.32/41). To keep the container/env/probes byte-identical between the two workloads, **first extract the pod `spec.template.spec` (or at least the container block) into a new `{{- define "worldview-service.podSpec" }}` helper in `_helpers.tpl`**, then `include` it from both `deployment.yaml` and `statefulset.yaml`. Do NOT copy-paste the container block (drift risk). This extraction is a prerequisite sub-step of this task, not a separate wave.

**Acceptance criteria**:
- [ ] `statefulSet.enabled: false` → only Deployment renders (existing behaviour byte-identical via `helm template`)
- [ ] `statefulSet.enabled: true` → only StatefulSet renders, with `volumeClaimTemplates: []`
- [ ] Pod spec (container, env, probes, resources) identical between variants (shared helper)

#### T-B-4-02: Add headless Service variant
**Type**: config
**depends_on**: [T-B-4-01]
**blocks**: [T-B-5-02]
**Target files**: `worldview-gitops/charts/worldview-service/templates/service.yaml` (add headless variant or companion template)
**PRD reference**: §6.5d, §9 "StatefulSet rollout stuck"

**What to build**: When `statefulSet.enabled`, render a headless Service (`clusterIP: None`) matching the StatefulSet selector + `serviceName`, required for stable pod DNS. Keep the existing ClusterIP Service for Deployment services.

**Acceptance criteria**:
- [ ] `statefulSet.enabled: true` renders a `clusterIP: None` Service whose name == StatefulSet `serviceName`
- [ ] Deployment path still renders the normal Service unchanged

#### T-B-4-03: Add instance-id downward-API env block (template support)
**Type**: config
**depends_on**: [T-B-4-01]
**blocks**: [T-B-5-02]
**Target files**: `worldview-gitops/charts/worldview-service/templates/_helpers.tpl` or the pod-spec env section used by both workloads
**PRD reference**: §3.1 FR-7, §6.5d

**What to build**: Support injecting an env var from `valueFrom.fieldRef: metadata.name` when configured in values (e.g. a `instanceIdEnv:` values key naming the target env var, defaulting unset → not rendered). This is the mechanism the prod overlay (W5) uses to set `<SVC>_KAFKA_CONSUMER_INSTANCE_ID` from the pod ordinal name. Only *stable* under StatefulSet (AD-3), but the template supports both.

**Acceptance criteria**:
- [ ] When `instanceIdEnv` is set, the pod spec renders `valueFrom.fieldRef.fieldPath: metadata.name` for that env var
- [ ] When unset, no such env is rendered (no behaviour change for existing services)

#### T-B-4-04: helm template / lint validation gate
**Type**: test
**depends_on**: [T-B-4-01, T-B-4-02, T-B-4-03]
**blocks**: none
**Target files**: (validation only — optionally a `charts/worldview-service/ci/` test-values file)
**PRD reference**: §11 "helm template lint"

**What to build**: Validate via `helm template` with two value sets (statefulSet on/off) + `helm lint` + kubeconform (if available in gitops CI). Confirm: off→Deployment only; on→StatefulSet + headless Service + fieldRef env + no PVC.

**Acceptance criteria**:
- [ ] `helm lint charts/worldview-service` clean
- [ ] `helm template` with `statefulSet.enabled=false` == prior render for an existing service (diff-clean)
- [ ] `helm template` with `statefulSet.enabled=true` renders StatefulSet + headless Service + fieldRef env, no `volumeClaimTemplates`
- [ ] kubeconform passes on both renders (if available)

#### Pre-read
- `worldview-gitops/charts/worldview-service/templates/deployment.yaml`
- `worldview-gitops/charts/worldview-service/templates/service.yaml`
- `worldview-gitops/charts/worldview-service/templates/_helpers.tpl`
- `worldview-gitops/charts/worldview-service/values.yaml`

#### Validation Gate
- [ ] `helm lint` clean
- [ ] `helm template` diff-clean for existing services (statefulSet off)
- [ ] StatefulSet render correct (headless Service, fieldRef env, no PVC)
- [ ] kubeconform passes (if in CI)
- [ ] No `secrets/*.yaml` touched (NFR-4)

#### Architecture Compliance
- [ ] R1 small diffs — chart change isolated from values changes (W5)
- [ ] secrets untouched (NFR-4)
- [ ] R10/R11/R12/R24/R32 — N/A (gitops yaml, no Python/Alembic)

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| existing per-service renders | `deployment.yaml` now guarded by `{{- if not statefulSet.enabled }}` | default `statefulSet.enabled: false` keeps all existing services on Deployment — verify diff-clean render |
| chart `ci/` snapshot tests (if any) | new template file | add statefulSet-on snapshot; keep off-snapshot identical |

#### Regression Guardrails
- **Diff-clean default**: the highest-risk regression is accidentally changing existing Deployment-backed services. T-B-4-04's "off == prior render" diff is the guard.
- **§9 "StatefulSet rollout stuck"**: headless Service + `volumeClaimTemplates: []` (OQ-8) prevent the Pending-pod failure mode.

---

### Wave 5: GitOps values/overlays (×7) + Bitnami provisioning + multi-broker

**Goal**: Land prod config divergence — Bitnami declarative topic provisioning (RF=3) + **multi-broker
scale-out (`broker.replicaCount:3`, `replicationFactor:3`, `controller.controllerOnly:true` — OQ-3/OQ-4)**,
and base+`.prod.yaml` overlays for Kafka + **ALL 7 consumer-running services** (OQ-7) with
`statefulSet.enabled`, instance-id fieldRef, and right-sized resources (FIX-2/3 prod + GAP-2). **Document the
RF-migration runbook caveat** (existing RF=1 topics cannot be upgraded by Helm).
**Depends on**: W4 (uses the StatefulSet variant + fieldRef env)
**Estimated effort**: 120 min
**Architecture layer**: gitops values / ArgoCD apps

> **DECIDED scope (OQ-7)**: the 7 consumer-running services each get a `values/<svc>.prod.yaml`:
> **alert, content-ingestion, content-store, knowledge-graph, market-data, nlp-pipeline, portfolio**
> (all 7 `values/<svc>.yaml` + `apps/worldview-<svc>.yaml` confirmed present in the gitops repo this
> session). The 3 non-consumer services (api-gateway, market-ingestion, rag-chat) keep a single values file.

#### Tasks

#### T-B-5-01: Multi-broker flip + Bitnami provisioning + broker config in infra-kafka.yaml
**Type**: config
**depends_on**: none
**blocks**: [T-B-5-06]
**Target files**: `worldview-gitops/apps/infra-kafka.yaml`
**PRD reference**: §3.1 FR-2/FR-3/FR-18, §6.6, §14 OQ-3/OQ-4

**What to build**: Three changes in `apps/infra-kafka.yaml`:
1. **Multi-broker flip (OQ-3/OQ-4)**: set `broker.replicaCount: 3`, the chart's `replicationFactor: 3`, and `controller.controllerOnly: true` (dedicated KRaft controller split from the 3 brokers). Verify the exact Bitnami 32.4.3 key names at implement time (`broker.replicaCount` / `controller.replicaCount` / `controller.controllerOnly` are the KRaft-mode keys).
2. **Provisioning**: add `provisioning.enabled: true` + `provisioning.topics[]` enumerating the **same topic set** as dev `create-topics.sh` (FR-3 parity) with **prod** (current/higher) partition counts and **`replicationFactor: 3` on every topic** (now valid because broker count = 3).
3. **Broker defaults**: **append** `num.partitions`, `offsets.topic.num.partitions`, `default.replication.factor=3`, `offsets.topic.replication.factor=3`, and `transaction.state.log.replication.factor=3` to the **existing** `extraConfig` literal (verified: it already carries `log.retention.hours=720` / `log.retention.bytes` / `message.max.bytes` — do NOT overwrite, append).

**Logic & Behavior**:
- Prod partitions = the *current* dev-pre-cut values (e.g. article/stored/enriched=12, signal=24, etc.) so nothing shrinks (Kafka cannot reduce; §9).
- RF=3 is now ≤ broker count (=3) so the provisioning-job failure mode (§9) does not fire on net-new topics.
- Idempotent create-if-not-exists semantics (NFR-5).
- **RF-MIGRATION CAVEAT (document as an inline YAML comment + in W6 docs)**: existing prod topics are RF=1 and Helm/provisioning **cannot raise RF on an already-existing topic**; RF=3 applies only to net-new topics or a fresh cluster. The operator runbook to upgrade existing topics (`kafka-reassign-partitions` per topic-partition, or fresh-cluster + mirror) is **DOCUMENTED, NOT executed here** — the prod cluster is not reachable from this work (see T-B-5-06 + §9).

**Acceptance criteria**:
- [ ] `broker.replicaCount: 3` + `replicationFactor: 3` + `controller.controllerOnly: true` set (exact keys verified against chart)
- [ ] `provisioning.enabled: true` + `topics[]` for the full topic set, every topic RF=3
- [ ] Topic names == dev `create-topics.sh` set (FR-3)
- [ ] `extraConfig` appends `num.partitions` + `offsets.topic.num.partitions` + the three `*.replication.factor=3` lines (existing retention/message lines preserved)
- [ ] RF-migration caveat present as an inline comment
- [ ] No `secrets/*.yaml` touched

#### T-B-5-02: Create base+prod overlay for ALL 7 consumer-running services
**Type**: config
**depends_on**: [T-B-4-01, T-B-4-02, T-B-4-03]
**blocks**: [T-B-5-04]
**Target files** (NEW `.prod.yaml` ×7 — base files already exist, keep dev-safe):
- `worldview-gitops/values/alert.prod.yaml`
- `worldview-gitops/values/content-ingestion.prod.yaml`
- `worldview-gitops/values/content-store.prod.yaml`
- `worldview-gitops/values/knowledge-graph.prod.yaml`
- `worldview-gitops/values/market-data.prod.yaml`
- `worldview-gitops/values/nlp-pipeline.prod.yaml`
- `worldview-gitops/values/portfolio.prod.yaml`
**PRD reference**: §3.1 FR-7/FR-12/FR-15, §6.5e, §7 AD-5, §14 OQ-7

**What to build**: For **each of the 7 consumer-running services** (DECIDED, OQ-7), keep the base `values/<svc>.yaml` dev-safe (low replicas, `statefulSet` absent/false) and add a new `values/<svc>.prod.yaml` that overrides only prod-divergent keys: right-sized `resources`, prod `replicaCount`, and — **for the services that run multi-replica static-membership consumers** — `statefulSet.enabled: true` + `instanceIdEnv: <SVC>_KAFKA_CONSUMER_INSTANCE_ID` (→ fieldRef `metadata.name` from W4 T-B-4-03).

**Logic & Behavior**:
- Last-file-wins Helm merge (AD-5) — each overlay carries only deltas (no full duplication of the base).
- **All 7 overlays** get right-sized `resources` + prod `replicaCount` (the universal prod divergence). Only the services whose consumers actually scale to >1 replica with static membership additionally set `statefulSet.enabled` + `instanceIdEnv` — start with nlp-pipeline (the article fleet); for the other 6, set `statefulSet.enabled` only where a consumer genuinely runs multi-replica in prod (verify each service's prod replica intent at implement time; a single-replica consumer can stay a Deployment with an empty instance id — no behaviour change).
- If a consumer runs as a distinct gitops app vs the main service, scope the StatefulSet to the consumer app only (verify the app/values topology at implement time).

**Acceptance criteria**:
- [ ] 7 `values/<svc>.prod.yaml` files created (alert, content-ingestion, content-store, knowledge-graph, market-data, nlp-pipeline, portfolio)
- [ ] Each base `values/<svc>.yaml` still renders a Deployment (dev-safe); each overlay carries only prod deltas
- [ ] Multi-replica static-membership consumers flip to StatefulSet + fieldRef instance-id in their overlay
- [ ] Right-sized `resources` present in every overlay

#### T-B-5-03: Right-size ML-service resources (prod audit)
**Type**: config
**depends_on**: none
**blocks**: [T-B-5-05]
**Target files**: `worldview-gitops/apps/infra-ollama.yaml`, `worldview-gitops/apps/infra-kafka.yaml` (resources section), any ML-service values
**PRD reference**: §3.1 FR-12, §10

**What to build**: Audit and adjust prod `resources` so Kafka retains guaranteed CPU headroom relative to ML pods on the same nodes (most app services already have requests/limits; infra-ollama/infra-kafka already carry resources — audit + adjust, do not regress). **With 3 brokers + a dedicated controller now scheduled (T-B-5-01), confirm the `node-role: stateful` nodes have enough aggregate CPU/memory for 3 broker pods + 1 controller pod + the ML pods**; surface (do not silently absorb) any node-capacity shortfall as a note for the operator.

**Acceptance criteria**:
- [ ] Kafka CPU `requests` ≥ a documented floor relative to ML pod requests on shared nodes
- [ ] Aggregate broker(×3)+controller(×1) resource requests fit the stateful node pool (or a capacity note is recorded)
- [ ] No resource regression vs current values

#### T-B-5-04: Wire .prod.yaml into ALL 7 consumer-service ArgoCD apps
**Type**: config
**depends_on**: [T-B-5-02]
**blocks**: [T-B-5-06]
**Target files** (×7):
- `worldview-gitops/apps/worldview-alert.yaml`
- `worldview-gitops/apps/worldview-content-ingestion.yaml`
- `worldview-gitops/apps/worldview-content-store.yaml`
- `worldview-gitops/apps/worldview-knowledge-graph.yaml`
- `worldview-gitops/apps/worldview-market-data.yaml`
- `worldview-gitops/apps/worldview-nlp-pipeline.yaml`
- `worldview-gitops/apps/worldview-portfolio.yaml`
**PRD reference**: §3.1 FR-15, §6.5e

**What to build**: In each of the 7 apps, change `valueFiles` from `[../../values/<svc>.yaml, secrets...]` to `[../../values/<svc>.yaml, ../../values/<svc>.prod.yaml, secrets...]` (last wins; the secrets entry stays last/untouched — NFR-4). If a consumer runs as a distinct app, wire that app too (verify topology at implement time).

**Acceptance criteria**:
- [ ] All 7 apps include their prod overlay before the secrets entry
- [ ] secrets entry unchanged in every app (NFR-4)

#### T-B-5-05: Document the RF-migration runbook caveat (gitops)
**Type**: docs
**depends_on**: [T-B-5-01]
**blocks**: none
**Target files**: `worldview-gitops/apps/infra-kafka.yaml` (inline comment, done in T-B-5-01) + `worldview-gitops/docs/` (the runbook note; cross-linked from W6 T-B-6-04)
**PRD reference**: §3.1 FR-2/FR-18, §9 "Existing prod topics stay RF=1", §14 RF-MIGRATION CAVEAT

**What to build**: Write the operational runbook note (NOT executed): existing prod topics are RF=1 and Helm/Bitnami provisioning **cannot raise RF on an already-existing topic**; the RF=3 values apply only to net-new topics or a fresh cluster. To upgrade existing topics an operator runs `kafka-reassign-partitions` (generate a reassignment JSON adding 2 replicas per topic-partition, then `--execute` + `--verify`) **or** stands up a fresh cluster and mirrors. State explicitly that **this PRD does NOT execute the runbook — the prod cluster is not reachable from this work**.

**Acceptance criteria**:
- [ ] Runbook note present in gitops docs (kafka-reassign-partitions OR fresh-cluster path)
- [ ] Note states the runbook is documented, NOT executed (prod unreachable)
- [ ] Cross-referenced from the W6 gitops doc (T-B-6-04) and §9

#### T-B-5-06: helm template / kubeconform validation gate
**Type**: test
**depends_on**: [T-B-5-01, T-B-5-03, T-B-5-04]
**blocks**: none
**Target files**: (validation only)
**PRD reference**: §11

**What to build**: `helm template` the affected apps with base+overlay; confirm StatefulSet + headless Service + fieldRef env render for the multi-replica consumers; confirm Kafka provisioning block + multi-broker values are valid; kubeconform clean across all 7 consumer apps + infra-kafka.

**Acceptance criteria**:
- [ ] `helm template` for each multi-replica consumer app (base+overlay) renders StatefulSet + headless Service + fieldRef instance-id
- [ ] `helm template` for the remaining consumer apps renders a Deployment with right-sized resources (no regression)
- [ ] infra-kafka renders `broker.replicaCount:3` + provisioning.topics at RF=3 (RF ≤ broker count) + `controller.controllerOnly:true`
- [ ] kubeconform clean across all 7 consumer apps + infra-kafka; no secrets touched

#### Pre-read
- `worldview-gitops/apps/infra-kafka.yaml`
- all 7 `worldview-gitops/values/<svc>.yaml` (alert, content-ingestion, content-store, knowledge-graph, market-data, nlp-pipeline, portfolio)
- all 7 `worldview-gitops/apps/worldview-<svc>.yaml` (same 7)
- `worldview-gitops/apps/infra-ollama.yaml`
- the W4 chart variant (T-B-4-01..03)

#### Validation Gate
- [ ] `helm template` base+overlay renders correctly for all 7 consumer apps
- [ ] Bitnami provisioning valid (RF=3 ≤ `broker.replicaCount:3`) + `controller.controllerOnly:true` renders
- [ ] kubeconform clean (7 consumer apps + infra-kafka)
- [ ] RF-migration runbook caveat documented (T-B-5-05)
- [ ] No `secrets/*.yaml` touched (NFR-4)

#### Architecture Compliance
- [ ] R1 small diffs — multi-broker flip / provisioning / each overlay / wiring as separate commits
- [ ] secrets untouched (NFR-4)
- [ ] R5/R8 — N/A (no schema/event change; partition count is not a schema property)

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| 7 ArgoCD consumer apps | valueFiles list grows | add overlay before secrets; verify ArgoCD merge order |
| existing infra-kafka render | provisioning block + multi-broker flip added | render must stay valid; RF=3 ≤ broker count (=3) |
| pre-existing prod RF=1 topics | Helm cannot raise RF on existing topics | NOT fixed by this PRD — operator runbook (T-B-5-05); RF=3 applies to net-new topics only |
| Deployment→StatefulSet transition for prod consumers | workload kind change | delete-Deployment/create-StatefulSet (brief consumer gap, acceptable for batch NLP — §12) |
| single-broker→3-broker transition in prod | broker pod count change + controller split | rolling-update via Bitnami chart; partitions rebalance is automatic for net-new, manual (reassign) for existing — see T-B-5-05 |

#### Regression Guardrails
- **§9 "provisioning job fails (RF > broker count)"**: RF=3 ≤ `broker.replicaCount:3` is the guard — the multi-broker flip (T-B-5-01) is what makes RF=3 legal.
- **§9 "Existing prod topics stay RF=1"**: the RF=3 values do NOT upgrade existing topics — the runbook (T-B-5-05) is the documented (not executed) remediation.
- **§9 "cannot reduce partitions"**: prod uses *current/higher* counts → nothing shrinks.
- **AD-3 stable identity**: an overlay must set `statefulSet.enabled` AND `instanceIdEnv` together — a Deployment + fieldRef would give an unstable id (buys nothing).

---

### Wave 6: Dev single-source-of-truth + docs + BP

**Goal**: Resolve GAP-1 (one authoritative dev config source + loud drift check + GENERATED banner), add the authoritative dev instance-id knobs, and complete all documentation incl. the new bug pattern and TRACKING update.
**Depends on**: W2/W3 (env knobs exist), W5 (overlay model to document)
**Estimated effort**: 75 min
**Architecture layer**: gitops scripts + docs (both repos)

> **W6 NOTE — dev static membership does NOT depend on docker.env (PLAN-0113 QA M5, verified 2026-06-17).**
> All 27 per-replica `*_CONSUMER_INSTANCE_ID` values are set via each numbered service's
> compose `environment:` block (T-A-3-01), which OVERRIDES `env_file: configs/docker.env`.
> Verified with `docker compose --profile all config` from `infra/compose/`: the rendered
> config carries every instance id (incl. nlp-pipeline `article-consumer-0/1`,
> `nlp-watchlist-0`, `nlp-entity-refresh-0`, `nlp-document-deletion-0`) REGARDLESS of what
> `docker.env` contains. The shared `docker.env` instance-id knobs are therefore NOT required
> for dev to function — they are belt-and-suspenders defaults that MUST stay empty (a single
> shared non-empty value would fence the fleet, BP-703). Consequently the W6 drift remediation
> deliberately leaves `services/<svc>/configs/docker.env` UNTOUCHED here (most of the observed
> drift is unrelated earlier-session edits that must not be reverted).

#### Tasks

#### T-B-6-01: Add check-dev-env-drift.sh (gitops)
**Type**: config
**depends_on**: none
**blocks**: [T-B-6-04]
**Target files**: `worldview-gitops/scripts/check-dev-env-drift.sh` (NEW)
**PRD reference**: §3.1 FR-14, §6.5f, §9 "drift check false-positive"

**What to build**: For each service, `diff env/dev/<svc>.env` against the live `../worldview/services/<svc>/configs/docker.env`, **ignoring the GENERATED banner line** (§9 false-positive mitigation). Exit non-zero on any diff, printing the offending service(s). Intended for the dev pre-flight and an optional make/CI target.

**Acceptance criteria**:
- [ ] Exits 0 when all in sync (banner ignored)
- [ ] Exits non-zero + names the service on injected drift
- [ ] Banner line difference alone does NOT trip the check

#### T-B-6-02: Add GENERATED banner to setup-dev.sh output
**Type**: config
**depends_on**: none
**blocks**: [T-B-6-01]
**Target files**: `worldview-gitops/scripts/setup-dev.sh`
**PRD reference**: §3.1 FR-14, §6.5f

**What to build**: Prepend a banner to each generated `docker.env`: `# GENERATED from worldview-gitops/env/dev/<svc>.env — DO NOT EDIT; run scripts/setup-dev.sh after editing the gitops source.` Ensure the drift check (T-B-6-01) ignores exactly this line.

**Acceptance criteria**:
- [ ] Every generated `docker.env` starts with the banner
- [ ] Banner format matches what the drift check ignores

#### T-B-6-03: Add authoritative dev instance-id knobs to env/dev
**Type**: config
**depends_on**: none
**blocks**: none
**Target files**: `worldview-gitops/env/dev/nlp-pipeline.env` (+ any other divergent service env)
**PRD reference**: §3.1 FR-8/FR-14, §6.6

**What to build**: Add the `*_INSTANCE_ID` knobs (and any dev resource knobs) to the authoritative `env/dev/<svc>.env`. The shared knob stays empty (per-replica distinctness lives in compose `environment:` overrides, T-A-3-01/02); this records the authoritative defaults so `setup-dev.sh` regenerates a consistent `docker.env`.

**Acceptance criteria**:
- [ ] `env/dev/nlp-pipeline.env` carries the new instance-id knob (empty default for the shared value)
- [ ] `setup-dev.sh` regeneration + drift check is green

#### T-B-6-04: GitOps docs — code/config split + overlay model + dev SoT
**Type**: docs
**depends_on**: [T-B-6-01]
**blocks**: none
**Target files**: `worldview-gitops/docs/` (new or existing doc), `worldview-gitops/README.md` (link)
**PRD reference**: §3.1 FR-13/FR-14/FR-15, §6.6, §7 AD-4/AD-5

**What to build**: Document (1) the code/config split (gitops owns config; FIX-2 code ships in worldview), (2) the base+`.prod.yaml` overlay model + last-wins merge (**all 7 consumer services**, OQ-7), (3) the dev single-source-of-truth (env/dev authoritative → generated docker.env → drift check, OQ-5 copy + CI drift check), (4) the DEV-vs-PROD matrix from PRD §6.6 incl. **prod multi-broker (3 brokers, RF=3, dedicated controller — OQ-3/OQ-4)**, and (5) the **RF-migration runbook caveat** (cross-link T-B-5-05).

**Acceptance criteria**:
- [ ] gitops doc covers code/config split, overlay model (7 services), dev SoT, dev/prod matrix, multi-broker, RF-migration caveat

#### T-B-6-05: worldview docs — BP-702 + TRACKING + BUG_PATTERNS
> **NOTE (shipped):** the BP number "BP-702" reserved below was already taken at
> commit time (watermark/outbox ordering pattern); this pattern shipped as
> **BP-703**. All "BP-702" mentions in this task refer to the shipped **BP-703**.
**Type**: docs
**depends_on**: none
**blocks**: none
**Target files**: `docs/BUG_PATTERNS.md` (add BP-702 → shipped as BP-703), `docs/plans/TRACKING.md` (status update), `docs/MASTER_PLAN.md` (if the dev/prod Kafka posture warrants a note)
**PRD reference**: §9 cross-ref, Compounding Check

**What to build**: Add **BP-702** (shipped as **BP-703**): single-node KRaft "partition-count × simultaneous-rebalance × CPU-starvation" controller-overload pattern ("all-green-then-flood" class), with the dev-tunes-down / prod-scales-out resolution and the `FencedInstanceIdException` static-membership pitfall. Update TRACKING.md status to reflect completed waves.

**Acceptance criteria**:
- [ ] BP-702 (shipped as BP-703) added with symptom / root cause / fix / guardrail
- [ ] TRACKING.md updated

#### Pre-read
- `worldview-gitops/scripts/setup-dev.sh`
- `worldview-gitops/env/dev/nlp-pipeline.env`
- `worldview-gitops/README.md`, `worldview-gitops/docs/`
- `docs/BUG_PATTERNS.md` (tail), `docs/plans/TRACKING.md`

#### Validation Gate
- [ ] `check-dev-env-drift.sh` self-test: green in sync, non-zero on injected drift
- [ ] `setup-dev.sh` + drift check round-trips green
- [ ] BP-702 (shipped as BP-703) + TRACKING + gitops docs updated

#### Architecture Compliance
- [ ] R1 small diffs — script / env / docs separable
- [ ] secrets untouched (NFR-4)
- [ ] R15 docs — all required docs updated this wave

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| existing `docker.env` files (no banner) | drift check compares to banner-less files until next setup-dev run | drift check ignores banner; document one-time `setup-dev.sh` re-run |
| any CI invoking setup-dev | now emits banner | banner is comment-only; harmless |

#### Regression Guardrails
- **§9 "drift check false-positive"**: banner-ignore logic is the guard; T-B-6-01 self-test injects drift to prove it works.
- **GAP-1 silent drift**: the whole wave exists to make drift loud — verify the check actually fails on a hand-edited `docker.env`.

---

## Cross-Cutting Concerns

- **Contract changes**: none (no Avro/API contract change — §6.2/6.3). FR-3 topic-name parity is the only cross-artifact invariant — a test asserts dev `create-topics.sh` names == prod `provisioning.topics` names.
- **Migration needs**: none (no Alembic — §6.4). R32 N/A.
- **Event flow changes**: partition counts (per env) + provisioning mechanism only; topic names unchanged; consumer membership semantics gain optional static membership.
- **Configuration changes**: new `kafka_*_consumer_instance_id` settings (default empty) per service; new dev env knobs in `env/dev/<svc>.env`; **7 new gitops `values/<svc>.prod.yaml` overlays (OQ-7)** wired into 7 ArgoCD apps; Bitnami provisioning (RF=3) + **multi-broker flip (`broker.replicaCount:3`, `controller.controllerOnly:true` — OQ-3/OQ-4)** + broker `extraConfig`.
- **Documentation updates**: `docs/libs/messaging.md` (W2), `docs/services/nlp-pipeline.md` + `.claude-context.md` (W3), gitops `docs/` (W6), `docs/BUG_PATTERNS.md` BP-702 → shipped as BP-703 (W6), `docs/plans/TRACKING.md` (W6).
- **Topic-name parity test (FR-3)**: lives in worldview (`tests/infra/`) but must read the gitops provisioning list — since gitops is a separate repo, the parity test either (a) hard-codes the canonical topic set asserted against `create-topics.sh`, or (b) is a documented manual/CI cross-repo check. Decide at W5/W6 implement time; default (a) (assert dev set against a canonical list also documented in gitops).

## Risk Assessment

- **Critical path**: W2 → W3 → W4 → W5 → W6. W1 and W4 are independently parallelizable.
- **Highest risk**: W5 prod scale-out — both the Deployment→StatefulSet transition for prod consumers AND the single-broker→3-broker + dedicated-controller flip (the behavioural prod changes; gated/declarative, revertible, brief consumer gap acceptable for batch NLP — §12). The chart diff-clean-when-off render (T-B-4-04) guards the non-consumer services; the **RF-migration caveat (T-B-5-05)** documents that existing RF=1 topics are NOT auto-upgraded (operator runbook, not executed). The 3 non-consumer services (api-gateway, market-ingestion, rag-chat) keep a single values file and are untouched by the overlay change.
- **Second risk**: NFR-3 byte-identity regression in W2 — mitigated by the omit-when-empty conditional + the unchanged existing `to_dict()` tests (R19).
- **Cross-repo coordination**: FIX-2 spans both repos (code in worldview, identity injection in gitops). The plan sequences code first (W2) so the field exists before any env sets it; default-empty means partial rollout is always safe.
- **Rollback strategy**: every code change is default-off/no-op (revert is a no-op for non-opting consumers); gitops overlay/StatefulSet is gated by `statefulSet.enabled` (flip false to revert to Deployment); dev partition cut requires a fresh KRaft volume to take effect (and to revert).
- **Cross-PRD coordination (non-blocking)**: PLAN-0109 sub-plan F-1 ("compose policy / compose hardening") and its "Kafka producer keepalive + reconnect" both edit `infra/compose/docker-compose.yml` and the messaging lib. PLAN-0113 W1 adds `deploy.resources` to gliner/ollama/kafka/postgres and W2 edits `libs/messaging` `ConsumerConfig`. The blocks are disjoint (0109 = restart/healthcheck policy + producer; 0113 = `deploy.resources` + consumer config), but if both run concurrently, **rebase 0113 W1/W2 onto 0109's compose/messaging changes** and re-run the parse-tests to avoid merge collisions. No design conflict.
- **Testing gaps**: dev cold-start NFR-1/NFR-2 are manual/E2E (`make dev` + `docker stats`) — not unit-testable; documented as manual acceptance in PRD §11.

## Compounding Check

- **New BP**: BP-702 (added in W6 T-B-6-05; **shipped as BP-703** — the reserved BP-702 number was already taken) — single-node KRaft partition×rebalance×CPU controller-overload + FencedInstanceIdException static-membership pitfall.
- **Docs**: messaging lib, nlp-pipeline service+context, gitops docs, BUG_PATTERNS, TRACKING — all scheduled in W2/W3/W6.
- **No RULES.md / STANDARDS.md change needed** (no new hard rule; existing R5/R8/R10/R11/R24/R25/R27 explicitly N/A and documented in §7.1).
