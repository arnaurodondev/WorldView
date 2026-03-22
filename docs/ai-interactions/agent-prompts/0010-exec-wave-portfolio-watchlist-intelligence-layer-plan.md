> **STATUS: IMPLEMENTED** — Both wave-01 and wave-02 fully implemented (2026-03-20). All 11 tasks complete.

# Execution Wave Plan 0010 — portfolio-watchlist-intelligence-layer

## Source Inputs

- Planning response: `docs/ai-interactions/agent-responses/0006-response-20260319-portfolio-watchlist-gap-analysis.md`
- Service: `services/portfolio/`
- Scope: Portfolio service (S1) — Watchlist management, alert preferences, entity_id linking, cache wiring, and pagination hardening

## Task Extraction

- Canonical task source: Section 5 (Prioritized Implementation Plan) of the response.
- Discovered task IDs:
  - W-001, W-002, W-003, W-004, W-005, W-006, W-007
  - C-001, C-002, C-003
  - B-001
  - F-001
- Duplicate IDs detected: none
- Coverage mode: full
- Tasks discovered: 12
- Max tasks per wave: 20
- Theoretical minimum waves (W_min): 1
- Actual waves: 2 (W_min + 1)
- Justification for extra wave: Domain + DB + messaging foundations (W-001 through W-005, B-001, F-001) must exist before API, cache, and alert preference layers (W-006, W-007, C-002, C-003) can be built on top of them.

## Generated Wave Files

- `docs/ai-interactions/agent-prompts/0010-exec-portfolio-watchlist-intelligence-layer-wave-01.md`
- `docs/ai-interactions/agent-prompts/0010-exec-portfolio-watchlist-intelligence-layer-wave-02.md`

## Wave Assignment Summary

- Wave 01 (foundations):
  - W-001 (watchlist domain entities + events)
  - C-001 (alert preference domain entities)
  - B-001 (entity_id on InstrumentRef)
  - F-001 (pagination for unbounded list endpoints)
  - W-002 (watchlist repo ABCs + UoW properties)
  - W-005 (watchlist Avro schemas + messaging)
  - W-003 (watchlist DB migration, ORM models, SQL repositories)
  - W-004 (watchlist use cases)

- Wave 02 (API, cache, alert preferences full stack):
  - C-002 (alert preference DB layer + migration)
  - W-006 (watchlist API endpoints — 7 routes)
  - W-007 (Valkey reverse-index cache — ValkeyClient wiring + WatchlistCachePort)
  - C-003 (alert preference use cases + API — 4 routes)

## Dependency Rationale

- Wave 01 builds all zero-dependency domain layers first (W-001, C-001, B-001, F-001), then repo ABCs (W-002), then DB infrastructure (W-003) and use cases (W-004) that depend on them, plus messaging schemas (W-005) that only depend on W-001 domain events.
- Wave 02 builds the API surface (W-006) and Valkey cache (W-007) on top of the use cases from wave-01, and implements the full alert preference stack (C-002 → C-003) after the domain from C-001.
- F-001 (pagination) is in wave-01 because it is an independent improvement and requires no new entities.

## Coverage Check

- assigned/discovered: 12/12
- exact-set match: passed
- unassigned tasks: none

## Coverage Ledger

| task_id | assigned_wave | status | dependency_note |
|---------|---:|---------|-----------------|
| W-001 | 01 | scheduled | No dependencies — domain entities |
| C-001 | 01 | scheduled | No dependencies — domain entities, parallel with W-001 |
| B-001 | 01 | scheduled | No dependencies — additive field on existing entity |
| F-001 | 01 | scheduled | No dependencies — independent pagination improvement |
| W-002 | 01 | scheduled | Depends on W-001 |
| W-005 | 01 | scheduled | Depends on W-001 domain events; parallel with W-002 |
| W-003 | 01 | scheduled | Depends on W-002 |
| W-004 | 01 | scheduled | Depends on W-002 (use cases need repo ABCs + FakeUoW) |
| C-002 | 02 | scheduled | Depends on C-001 |
| W-006 | 02 | scheduled | Depends on W-004 (use cases) and W-005 (schemas) |
| W-007 | 02 | scheduled | Depends on W-004 (use cases call cache port) and W-006 (wires dependency) |
| C-003 | 02 | scheduled | Depends on C-002 |

## Documentation requirement (mandatory for both waves)

Every task that introduces or changes API endpoints, DB schema, Kafka topics, Avro schemas, config vars, or observable behavior must update `docs/services/portfolio.md` in the same wave. The doc must reflect the final implemented state — not a future plan — before the wave is marked done.

Full coverage unit tests, integration tests, and contract tests are mandatory for every new feature. No task is complete without its required tests passing. See per-task test requirements in the wave files.
