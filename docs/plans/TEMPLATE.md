---
id: PLAN-NNNN
prd: PRD-NNNN
title: "<Feature Title> — Implementation Plan"
status: draft | approved | in-progress | completed | cancelled
created: YYYY-MM-DD
updated: YYYY-MM-DD
plans: 0
waves: 0
tasks: 0
---

# PLAN-NNNN: <Feature Title>

## Overview

**PRD Reference**: [PRD-NNNN](../specs/NNNN-slug.md)
**Goal**: <One-sentence summary of what this implementation achieves>
**Total Scope**: <N> sub-plans, <N> waves, <N> tasks

---

## Plan Dependency Graph

```
Plan A: <Infrastructure/Schema> ──┐
                                  ├──→ Plan C: <Service X>
Plan B: <Shared Libraries>  ─────┘         │
                                           ├──→ Plan E: <Frontend>
                                  ┌────────┘
Plan D: <Service Y>  ────────────┘
```

**Execution Order**:
1. Plan A (infrastructure) — no dependencies
2. Plan B (libraries) — no dependencies, parallel with A
3. Plan C (Service X) — depends on A + B
4. Plan D (Service Y) — depends on A + B
5. Plan E (Frontend) — depends on C + D

---

## Sub-Plan A: <Infrastructure / Schema Changes>

### Context
<Why this plan exists as a separate unit and what it accomplishes>

### Pre-Read (agent must read before any wave)
- `docs/MASTER_PLAN.md` (relevant sections)
- `RULES.md`
- `infra/kafka/schemas/` (existing schemas)
- `docs/ai-interactions/BUG_PATTERNS.md`

---

### Wave A-1: <Wave Title>

**Goal**: <One-sentence description>
**Depends on**: none
**Estimated effort**: 30-60 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-A-1-01 | <Description> | schema | `infra/kafka/schemas/X.avsc` | Schema validates with fastavro, forward-compatible |
| T-A-1-02 | <Description> | config | `docker-compose.yml`, `infra/kafka/init/` | Topic created on init, partition count matches design |
| T-A-1-03 | <Description> | docs | `docs/services/X.md` | Schema section updated with new event |

#### Pre-Read
- `infra/kafka/schemas/` — existing schemas for reference
- `infra/kafka/init/` — topic creation scripts

#### Validation Gate
- [ ] `./scripts/gen-contracts.sh` passes
- [ ] Avro schema JSON valid
- [ ] Schema forward-compatible (no field removals, new fields have defaults)
- [ ] Documentation updated

#### Regression Guardrails
- BP-001: OutboxKafkaValue serialization — ensure new schema is compatible with outbox format

---

### Wave A-2: <Wave Title>

**Goal**: ...
**Depends on**: Wave A-1
**Estimated effort**: ...

#### Tasks
| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| ... | ... | ... | ... | ... |

#### Validation Gate
- [ ] ...

---

## Sub-Plan B: <Shared Library Changes>

### Context
<Why this plan exists>

### Pre-Read
- `docs/libs/<lib>.md`
- `libs/<lib>/src/`

---

### Wave B-1: <Wave Title>

(Same structure as above)

---

## Sub-Plan C: <Service X Implementation>

### Context
<Why this plan exists>

### Pre-Read
- `docs/services/<service>.md`
- `services/<service>/.claude-context.md`
- `services/<service>/src/<service>/domain/`
- `docs/ai-interactions/BUG_PATTERNS.md`

---

### Wave C-1: <Domain Layer>

**Goal**: Define domain entities, value objects, and events
**Depends on**: Plan A (schemas exist), Plan B (lib changes available)
**Estimated effort**: 30-45 minutes

#### Tasks
| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-C-1-01 | Create domain entity | impl | `services/X/src/X/domain/entities/` | Entity has all required fields, validates invariants |
| T-C-1-02 | Create value objects | impl | `services/X/src/X/domain/value_objects.py` | Value objects are immutable, validate on construction |
| T-C-1-03 | Define domain events | impl | `services/X/src/X/domain/events.py` | Events match Avro schema structure |
| T-C-1-04 | Unit tests for domain | test | `services/X/tests/unit/domain/` | All entity invariants tested, edge cases covered |

#### Validation Gate
- [ ] `ruff check services/X/src/X/domain/` passes
- [ ] `mypy services/X/src --config-file mypy.ini` passes
- [ ] `python -m pytest services/X/tests -m "unit" -v` passes
- [ ] Domain layer has zero infrastructure imports

---

### Wave C-2: <Application Layer>

**Goal**: Implement use cases and port interfaces
**Depends on**: Wave C-1
**Estimated effort**: 45-60 minutes

#### Tasks
| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-C-2-01 | Define port interfaces | impl | `services/X/src/X/application/ports/` | Ports are abstract (Protocol or ABC) |
| T-C-2-02 | Implement use case | impl | `services/X/src/X/application/use_cases/` | Use case orchestrates domain + ports |
| T-C-2-03 | Unit tests for use cases | test | `services/X/tests/unit/application/` | Use cases tested with mocked ports |

---

### Wave C-3: <Infrastructure Layer>

**Goal**: Implement adapters (DB, Kafka, external APIs)
**Depends on**: Wave C-2
**Estimated effort**: 45-75 minutes

(Same structure)

---

### Wave C-4: <API Layer + Integration>

**Goal**: Wire everything together with API endpoints
**Depends on**: Wave C-3
**Estimated effort**: 45-60 minutes

(Same structure, includes integration tests)

---

## Cross-Cutting Concerns

### Contract Changes
| Type | Item | Compatibility | Test |
|------|------|--------------|------|
| Avro | `X.avsc` | Forward-compatible | `tests/contract/test_X.py` |
| REST | `POST /api/v1/X` | New endpoint | E2E test |

### Migrations
| Service | Migration | Description | Order |
|---------|-----------|-------------|-------|
| X | `NNNN_add_X_table.py` | Creates X table with columns... | After Plan A |

### Configuration
| Service | Env Var | Default | Purpose |
|---------|---------|---------|---------|
| X | `X_FEATURE_ENABLED` | `true` | Feature toggle |

### Documentation Updates
| Document | Update Required |
|----------|----------------|
| `docs/services/X.md` | New endpoints, events, data model |
| `docs/MASTER_PLAN.md` | Only if system-wide change |
| `services/X/.claude-context.md` | New endpoints, topics, entities |

---

## Risk Assessment

### Critical Path
<Which plan/wave blocks the most downstream work?>

### Highest Risk
| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| ... | ... | ... | ... |

### Rollback Strategy
<If a plan fails mid-way, how to recover>

---

## Tracking

### Plan Status
| Plan | Status | Waves Done | Waves Total |
|------|--------|-----------|-------------|
| A: Infrastructure | pending | 0 | 2 |
| B: Libraries | pending | 0 | 1 |
| C: Service X | pending | 0 | 4 |
| D: Service Y | pending | 0 | 3 |
| E: Frontend | pending | 0 | 2 |

### Wave Status
| Wave | Status | Tasks Done | Tasks Total | Blockers |
|------|--------|-----------|-------------|----------|
| A-1 | pending | 0 | 3 | none |
| A-2 | pending | 0 | 2 | A-1 |
| B-1 | pending | 0 | 3 | none |
| C-1 | pending | 0 | 4 | A, B |
| C-2 | pending | 0 | 3 | C-1 |
| C-3 | pending | 0 | 4 | C-2 |
| C-4 | pending | 0 | 3 | C-3 |
| ... | ... | ... | ... | ... |

### Task Status Legend
- `pending` — Not started
- `in-progress` — Currently being implemented
- `done` — Completed and validated
- `blocked` — Waiting on dependency or issue
- `cancelled` — No longer needed
