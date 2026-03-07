# CLAUDE.md — Claude-Specific Operating Guide

> **Purpose**: Tailored instructions for Claude (Anthropic) when working in this repo.
> Extends `AGENTS.md` with Claude-specific workflow preferences.

---

## Read First

1. `AGENTS.md` — general agent guide (coding standards, checklists, architecture)
2. `RULES.md` — hard rules (MUST/NEVER)
3. `docs/MASTER_PLAN.md` — full system architecture
4. The relevant `docs/services/<service>.md` for the service you're modifying

## Claude-Specific Workflow

### Prefer Small, Focused Diffs
- Make one logical change per edit. Do not combine unrelated changes.
- If a task requires changes across multiple services, make each service's changes
  independently and verify each one before moving to the next.
- Keep refactors separate from feature work.

### Always Run Tests
- After every code change, run the relevant tests:
  ```bash
  cd services/<service> && make test
  ```
- If you add a new function or class, add a test immediately — do not defer.
- For integration tests requiring infra, verify infra is running first.

### Keep Documentation Updated
- If you change an API endpoint, update `docs/services/<service>.md`.
- If you change a Kafka event, update the Avro schema AND the service doc.
- If you add a new config variable, update `configs/dev.local.env.example`.
- Update `docs/MASTER_PLAN.md` only for system-wide architectural changes.

### Never Change Contracts Without Versioning
- **Avro schemas**: add new fields with defaults. Never remove or rename fields.
  Bump `schema_version` in the envelope when adding fields.
- **REST APIs**: add new endpoints freely. For breaking changes to existing endpoints,
  create a new version path (`/api/v2/...`).
- **Kafka topics**: never rename. To change semantics, create a new topic version
  (e.g., `content.article.raw.v2`).

### Database Migrations
- Always create an Alembic migration for schema changes:
  ```bash
  cd services/<service> && alembic revision --autogenerate -m "description"
  ```
- Review the generated migration — autogenerate is not always correct.
- Migrations must be backwards-compatible (additive only in production).

### Logging
- Use `structlog` exclusively. Example:
  ```python
  import structlog
  logger = structlog.get_logger()

  logger.info("event_description", key1="value1", key2=42)
  ```
- Always include contextual fields: `service`, `correlation_id`, `tenant_id`.
- Never log secrets, API keys, tokens, or PII.

### Error Handling
- Classify errors: `RetryableError` vs `FatalError` (use `libs/messaging` hierarchy).
- Retryable: network timeouts, 5xx from upstream, DB connection errors.
- Fatal: schema validation failures, malformed data, business rule violations.
- Use structured error responses (see `docs/MASTER_PLAN.md` § API Contracts).

### Common Pitfalls to Avoid
1. **Naive datetimes**: Always use `datetime.now(tz=timezone.utc)` or `libs/common` helpers.
2. **Direct DB cross-service access**: Services own their DB. Use Kafka events or REST.
3. **Dual writes**: Never write to DB and publish to Kafka in separate transactions.
   Use the outbox pattern from `libs/messaging`.
4. **Hardcoded config**: All config via `pydantic-settings` with env vars.
5. **Blocking calls in async context**: Use `asyncio` properly; never call sync I/O
   in an `async def` without `run_in_executor`.
6. **Missing idempotency**: Every Kafka consumer must handle re-delivery gracefully.

### Frontend (apps/frontend)
- The frontend talks **only** to S9 API Gateway — never to backend services directly.
- Use TanStack Query for all server-state fetching.
- Add types for all gateway responses in `src/lib/gateway-client.ts`.
- Run `pnpm typecheck` before committing TypeScript changes.
- Unit tests go in `tests/`, E2E tests in `e2e/`.

### When Uncertain
- Check how the existing services (Portfolio, Market Ingestion, Market Data) solved
  a similar problem. They are the reference implementations.
- If the pattern doesn't exist yet, propose it as a small ADR before implementing.
- Prefer the simplest solution that maintains the architectural invariants.
