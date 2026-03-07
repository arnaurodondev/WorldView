# RULES.md — Hard Rules for the Worldview Platform

> **Purpose**: Non-negotiable rules for all contributors (human and AI).
> Every rule has a short "why" — understanding the reason prevents circumvention.

---

## Testing Rules

### R1: MUST add or update tests for every behavior change
**Why**: Untested code is unknown code. The thesis demo cannot afford regressions.
Every new function, endpoint, consumer, or domain rule needs at least one unit test.
Integration tests are required for database operations and Kafka flows.

### R2: MUST run `scripts/lint.sh` and `scripts/test.sh` before committing
**Why**: Broken code must never reach `main`. Lint catches style drift and security
issues. Tests catch logic errors. Both are enforced in CI, but catching locally saves
time and CI minutes.

---

## Documentation Rules

### R3: MUST update docs when behavior or contracts change
**Why**: Stale docs are worse than no docs — they actively mislead. If you change an
API, event schema, or internal workflow, the corresponding doc in `docs/services/`,
`docs/libs/`, or `docs/MASTER_PLAN.md` must be updated in the same PR.

### R4: MUST write an ADR before adding a new service or major architectural change
**Why**: Architectural decisions are expensive to reverse. An ADR forces you to
articulate context, alternatives, and consequences. Use `docs/architecture/decisions/ADR_TEMPLATE.md`.

---

## Contract Rules

### R5: MUST version Avro schemas and ensure forward compatibility
**Why**: Kafka consumers deployed independently. If a producer changes its schema
without forward compatibility, all consumers break simultaneously. Rules:
- Add new fields with **default values** only
- Never remove or rename existing fields
- Bump `schema_version` in the event envelope
- Run `scripts/gen-contracts.sh` to validate compatibility before merging

### R6: MUST version REST API paths for breaking changes
**Why**: Clients (frontend, other services) depend on stable API contracts.
Non-breaking additions (new endpoints, new optional fields) are fine. Breaking changes
(renamed fields, changed semantics, removed endpoints) require a new version path
(`/api/v2/...`) and a deprecation period.

---

## Architecture Rules

### R7: MUST NOT access another service's database directly
**Why**: Database ownership is the foundation of microservice independence. If
service A queries service B's database, they are coupled at the schema level — any
migration in B can break A. Communicate via:
- **Kafka events** for async state propagation
- **REST API calls** for synchronous queries

### R8: MUST NOT perform dual writes (DB + Kafka in separate transactions)
**Why**: If the DB write succeeds but Kafka publish fails (or vice versa), the system
is in an inconsistent state. Use the **transactional outbox pattern** from
`libs/messaging`: write the event to the `outbox_events` table in the same DB
transaction, then let the dispatcher publish it to Kafka.

### R9: MUST make Kafka consumers idempotent
**Why**: Kafka guarantees at-least-once delivery. Consumers will see duplicate events
during rebalances, retries, or network hiccups. Every consumer must:
- Check `event_id` against a processed-events table before processing
- Use upsert (INSERT ON CONFLICT) for materializations
- Be safe to re-run on the same event

### R10: MUST use UUIDv7 for all entity IDs
**Why**: UUIDv7 is time-sortable (natural ordering in indexes), globally unique
(no coordination needed), and embeds a timestamp (useful for debugging). Never use
auto-increment integers (leak information, can't merge across services) or UUIDv4
(random, poor index locality).

### R11: MUST enforce UTC-only timestamps
**Why**: Timezone bugs are subtle and devastating in financial data. All timestamps
in the system are UTC timezone-aware (`datetime` with `tzinfo=timezone.utc`). Naive
datetimes raise `ValueError` via `libs/common` helpers. Database columns use
`TIMESTAMPTZ`. JSON serialization uses ISO-8601 with `Z` suffix.

### R12: MUST use claim-check pattern for large Kafka payloads
**Why**: Kafka is optimized for small messages (~1KB). Sending multi-MB payloads
(OHLCV datasets, full articles) through Kafka increases broker memory pressure,
consumer lag, and rebalance times. Store the payload in MinIO, send a pointer event
with `(bucket, key, content_type, etag)`.

---

## Security Rules

### R13: MUST NOT embed secrets in code or config files
**Why**: Secrets in code end up in Git history, CI logs, and error traces. Use:
- Environment variables loaded via `pydantic-settings`
- `configs/dev.local.env.example` as a template (never the actual `.env`)
- GitHub Actions secrets for CI

### R14: MUST sanitize logs — never log secrets, API keys, tokens, or PII
**Why**: Logs are stored, indexed, and often accessible to broad teams. A leaked API
key in a log line can be exploited. Use the log sanitization pattern from
`libs/observability` to strip `sk-*`, `Bearer *`, `api_key=*` patterns.

### R15: MUST validate and sanitize all external input
**Why**: The Content Service fetches from untrusted RSS feeds and web pages. The
RAG service processes user queries. Without validation:
- SSRF: a crafted URL could hit internal services
- Injection: malicious input could manipulate LLM prompts or SQL
- XSS: unsanitized HTML could execute in the frontend
Use Pydantic models for request validation, domain allowlists for URLs, and input
length limits for all user-facing text fields.

---

## Process Rules

### R16: MUST NOT add a new microservice without an ADR
**Why**: Each microservice adds operational overhead (deployment, monitoring, testing,
inter-service communication). The decision to split or merge services must be
deliberate and documented.

### R17: CI MUST pass before merge to main
**Why**: `main` is the deployable branch. A broken `main` blocks everyone. CI runs:
lint, type-check, unit tests, contract tests, and Avro schema compatibility checks.
No exceptions.

### R18: MUST follow the branching convention
**Why**: Consistent branch naming enables CI automation and makes the Git log readable.
- Feature branches: `feat/<short-description>`
- Bug fixes: `fix/<short-description>`
- Docs: `docs/<short-description>`
- Refactors: `refactor/<short-description>`

---

## Summary Table

| Rule | Category | Severity |
|------|----------|----------|
| R1 | Testing | MUST |
| R2 | Testing | MUST |
| R3 | Documentation | MUST |
| R4 | Documentation | MUST |
| R5 | Contracts | MUST |
| R6 | Contracts | MUST |
| R7 | Architecture | MUST NOT |
| R8 | Architecture | MUST NOT |
| R9 | Architecture | MUST |
| R10 | Architecture | MUST |
| R11 | Architecture | MUST |
| R12 | Architecture | MUST |
| R13 | Security | MUST NOT |
| R14 | Security | MUST |
| R15 | Security | MUST |
| R16 | Process | MUST NOT |
| R17 | Process | MUST |
| R18 | Process | MUST |
