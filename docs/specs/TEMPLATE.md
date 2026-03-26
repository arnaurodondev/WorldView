---
id: PRD-NNNN
title: "<Feature Title>"
status: draft | in-review | approved | in-progress | completed | cancelled
created: YYYY-MM-DD
updated: YYYY-MM-DD
author: "human + claude"
services: []
priority: P0 | P1 | P2 | P3
estimated-waves: 0
---

# PRD-NNNN: <Feature Title>

## 1. Problem Statement

### 1.1 Background
<Context: what exists today and why it's insufficient>

### 1.2 Problem
<Clear, specific description of the problem being solved>

### 1.3 Business Value
<Why solving this matters — user impact, thesis goals, system capability>

---

## 2. Users & Use Cases

### 2.1 Target Users
| User Type | Description | Primary Need |
|-----------|-------------|--------------|
| ... | ... | ... |

### 2.2 Use Cases
| ID | As a... | I want to... | So that... | Priority |
|----|---------|-------------|------------|----------|
| UC-1 | ... | ... | ... | must-have |
| UC-2 | ... | ... | ... | nice-to-have |

### 2.3 User Flows
<Describe the step-by-step flow for the primary use case>

---

## 3. Functional Requirements

| ID | Requirement | Priority | Use Case |
|----|------------|----------|----------|
| FR-1 | ... | must-have | UC-1 |
| FR-2 | ... | must-have | UC-1 |
| FR-3 | ... | nice-to-have | UC-2 |

---

## 4. Non-Functional Requirements

| ID | Requirement | Target Metric | Rationale |
|----|------------|---------------|-----------|
| NFR-1 | Latency | <200ms p95 | User experience |
| NFR-2 | Throughput | >100 req/s | Expected load |
| NFR-3 | Availability | 99.5% | Thesis demo reliability |

---

## 5. Out of Scope

- <What this feature explicitly does NOT include>
- <Deferred items for future PRDs>

---

## 6. Technical Design

### 6.1 Affected Services

| Service | Changes | Impact Level | Notes |
|---------|---------|-------------|-------|
| S1 Portfolio | ... | HIGH/MED/LOW | ... |

### 6.2 API Changes

#### New Endpoints
| Method | Path | Request | Response | Auth |
|--------|------|---------|----------|------|
| POST | /api/v1/... | `{...}` | `{...}` | required |

#### Modified Endpoints
| Endpoint | Change | Backward Compatible? |
|----------|--------|---------------------|
| ... | ... | yes/no |

### 6.3 Event Changes

#### New Kafka Topics
| Topic Name | Schema | Producers | Consumers | Retention |
|-----------|--------|-----------|-----------|-----------|
| `domain.entity.verb_past` | `entity_event.avsc` | S1 | S3, S5 | 7d |

#### New Avro Schema Fields
| Schema | Field | Type | Default | Purpose |
|--------|-------|------|---------|---------|
| ... | ... | ... | ... | ... |

### 6.4 Database Changes

#### New Tables
| Service DB | Table | Columns (key) | Indexes | Notes |
|-----------|-------|---------------|---------|-------|
| ... | ... | id (PK), ... | ... | ... |

#### Modified Tables
| Table | Change | Migration Strategy |
|-------|--------|-------------------|
| ... | Add column X | Additive, default value, no downtime |

### 6.5 Domain Model Changes

#### New Entities
| Entity | Key Attributes | Invariants |
|--------|---------------|------------|
| ... | id, name, status | Status transitions: draft→active→archived |

#### New Value Objects
| Value Object | Fields | Validation |
|-------------|--------|------------|
| ... | ... | ... |

#### New Enums
| Enum | Values | Used By |
|------|--------|---------|
| ... | ... | ... |

### 6.6 Frontend Changes

| Component | Type | Description |
|-----------|------|-------------|
| ... | page/component/hook | ... |

### 6.7 Data Flow

#### Request Path
```
User Action → Frontend → API Gateway (S9) → Target Service → DB → Response
```

#### Event Path
```
Producer Service → Kafka Topic → Consumer Service(s) → Side Effects
```

#### Query Path
```
Frontend → API Gateway → Service → DB/Cache → Aggregated Response
```

---

## 7. Architecture Decisions

| # | Decision | Alternatives Considered | Trade-offs | Rationale |
|---|----------|------------------------|------------|-----------|
| AD-1 | ... | A: ..., B: ... | A is simpler but B scales better | Chose A because thesis scope doesn't need scale |

---

## 8. Security Analysis

### 8.1 Threat Model
| Threat | Likelihood | Impact | Mitigation |
|--------|-----------|--------|------------|
| ... | HIGH/MED/LOW | HIGH/MED/LOW | ... |

### 8.2 Input Validation
| Entry Point | Data Source | Validation Required |
|-------------|------------|-------------------|
| ... | ... | ... |

### 8.3 Authorization
| Operation | Required Permission | Enforcement Point |
|-----------|-------------------|------------------|
| ... | ... | API middleware |

### 8.4 Multi-Tenant Isolation
<How tenant isolation is maintained for this feature>

---

## 9. Failure Modes & Recovery

| # | Scenario | Probability | Impact | Detection | Recovery |
|---|----------|------------|--------|-----------|----------|
| F-1 | Kafka down during event publish | LOW | MED | Outbox retry | Outbox dispatcher retries |
| F-2 | ... | ... | ... | ... | ... |

---

## 10. Scalability & Performance

### 10.1 Expected Volumes
| Metric | Current | After Feature | Growth Rate |
|--------|---------|--------------|-------------|
| ... | ... | ... | ... |

### 10.2 Bottleneck Analysis
| Bottleneck | Risk Level | Mitigation |
|-----------|-----------|------------|
| ... | ... | Caching / Indexing / Pagination |

---

## 11. Test Strategy

### 11.1 Unit Tests
| Area | Test Focus | Priority |
|------|-----------|----------|
| Domain entities | Invariant validation, state transitions | HIGH |

### 11.2 Integration Tests
| Scenario | Services Involved | Infrastructure |
|----------|------------------|---------------|
| ... | S1, S3 | PostgreSQL, Kafka |

### 11.3 E2E Tests
| Flow | Entry Point | Expected Outcome |
|------|------------|-----------------|
| ... | API request | ... |

### 11.4 Contract Tests
| Contract | Type | Scope |
|----------|------|-------|
| Avro schema X | Forward-compatibility | ... |

---

## 12. Migration Plan

### 12.1 Backward Compatibility
<How existing functionality is preserved during rollout>

### 12.2 Rollback Strategy
<How to revert if something goes wrong>

### 12.3 Data Migration
<Any data transformation or backfill needed>

---

## 13. Observability

### 13.1 Metrics
| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| ... | counter/gauge/histogram | service, operation | ... |

### 13.2 Logging
| Event | Level | Fields | Purpose |
|-------|-------|--------|---------|
| ... | INFO/WARN/ERROR | ... | ... |

### 13.3 Alerting
| Alert | Condition | Severity | Action |
|-------|-----------|----------|--------|
| ... | ... | ... | ... |

---

## 14. Open Questions

| # | Question | Owner | Deadline | Resolution |
|---|----------|-------|----------|------------|
| Q-1 | ... | ... | ... | pending |

---

## 15. Implementation Estimation

| Aspect | Estimate |
|--------|----------|
| Number of plans | ... |
| Number of waves | ... |
| Total tasks | ... |
| Critical path | Plan X → Plan Y → Plan Z |
| Key risk | ... |

---

## Changelog

| Date | Author | Change |
|------|--------|--------|
| YYYY-MM-DD | ... | Initial draft |
