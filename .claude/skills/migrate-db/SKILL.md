---
name: migrate-db
description: "Generate and validate an Alembic migration for entity/model changes. Checks if a migration is needed, generates it, validates forward-compatibility, tests rollback, and guards against intelligence_db DDL violations (R24). Surfaces automatically when editing entity, model, or Alembic files."
user-invocable: true
argument-hint: "[service name or migration description, e.g. 'portfolio add watchlist table']"
effort: medium
paths:
  - "**/alembic/**"
  - "**/entities/**/*.py"
  - "**/value_objects.py"
  - "**/infrastructure/db/models.py"
---

# Migrate DB — Alembic Migration Workflow

You are a **Database Engineer** managing Alembic schema migrations in the worldview platform. You apply a rigorous process to ensure migrations are forward-compatible, reversible, and correctly scoped to the right service's ownership boundary.

## Input

Migration scope: `$ARGUMENTS`

---

## Step 1 — Context & Ownership Check

1. Identify the target service from the argument or recently-edited files
2. Read `services/<service>/.claude-context.md` for DB name and Alembic status
3. **Critical ownership guard** (R24 / `intelligence_db` rule):
   - If the target service is **S6 (`nlp-pipeline`)** or **S7 (`knowledge-graph`)**: STOP.
     These services have `ALEMBIC_ENABLED=false`. DDL for `intelligence_db` is owned exclusively by `intelligence-migrations`. Direct any schema changes there.
   - If target is **`intelligence-migrations`**: proceed normally (it is the DDL owner)
4. Read `services/<service>/alembic/env.py` — verify `Base.metadata` is wired correctly
5. Check existing migrations: `ls services/<service>/alembic/versions/`
6. Read `docs/BUG_PATTERNS.md` for any migration-related patterns

---

## Step 2 — Determine if Migration Is Needed

Run autogenerate comparison to detect schema drift:

```bash
cd services/<service>
# Check current head vs database (needs running DB)
alembic check 2>&1 || true

# Generate autogenerate output (dry run, review before applying)
alembic revision --autogenerate --message "<description>" --rev-id preview_$(date +%s)
```

Review the generated migration for:
- Only contains changes for THIS service's tables (no cross-service contamination)
- No accidental `drop_table` or `drop_column` operations (forward-compat rule)
- Proper nullable defaults for new columns (adding non-nullable without default is a breaking change)
- Indexes are created `IF NOT EXISTS`
- Sequences use correct naming convention

**If no schema drift detected**: inform the user and exit. Do not generate a no-op migration.

---

## Step 3 — Forward-Compatibility Validation

Before applying, verify the migration does NOT violate forward-compatibility (Rule 11):

**ALLOWED operations:**
- `ADD COLUMN` with `nullable=True` OR a non-null default
- `CREATE TABLE`
- `CREATE INDEX` / `CREATE INDEX CONCURRENTLY`
- `ALTER COLUMN ... TYPE` only for widening changes (VARCHAR(50) → VARCHAR(255), INT → BIGINT)
- `ADD CONSTRAINT` with `NOT VALID` to defer validation

**FORBIDDEN without explicit user approval:**
- `DROP COLUMN`
- `DROP TABLE`
- `RENAME COLUMN` or `RENAME TABLE`
- `ALTER COLUMN ... NOT NULL` on existing column without default
- `DROP INDEX` on a production index

If any forbidden operation is detected:
1. Show the operation to the user
2. Ask: "This operation is destructive and may break running services. Confirm?"
3. Only proceed on explicit confirmation

---

## Step 4 — Generate Final Migration

```bash
cd services/<service>

# Generate with descriptive message
alembic revision --autogenerate \
  --message "<service>: <description of change>"

# Review the generated file
cat alembic/versions/<rev_id>_<message>.py
```

Verify the generated file:
- Has both `upgrade()` and `downgrade()` implemented
- `downgrade()` correctly reverses `upgrade()` (for rollback testing)
- No stray `print()` or debug statements
- Imports are minimal and correct

---

## Step 5 — Rollback Test

Test that `downgrade` works without errors (uses a test database, not production):

```bash
cd services/<service>

# Apply the migration
alembic upgrade head

# Test rollback
alembic downgrade -1

# Re-apply to confirm idempotency
alembic upgrade head
```

If rollback fails: fix the `downgrade()` function before proceeding.

---

## Step 6 — intelligence-migrations Guard

If any migration touches the `intelligence_db` schema (even legitimately via `intelligence-migrations`):

1. Check that `intelligence-migrations/alembic/versions/` is the target, not a service
2. Read `intelligence-migrations/src/intelligence_migrations/` to understand current schema
3. Verify the migration doesn't conflict with S7's materialized view refresh workers

---

## Step 7 — Documentation Update

1. Update `services/<service>/.claude-context.md`:
   - Add new tables/columns to the "Key Entities" section
   - Update "Process Topology" if new processes are introduced

2. Update `docs/services/<service>.md`:
   - Add new columns to data model section
   - Document any schema version bump

3. If this migration changes an API-visible field:
   - Check if any Avro schema needs updating (`infra/kafka/schemas/*.avsc`)
   - If yes: invoke schema-guard validation

---

## Compounding Check

- New migration file added → verified forward-compatible + rollback tested
- No intelligence_db DDL violations
- Service doc updated with schema change
- `.claude-context.md` updated if entities changed
- No `DROP COLUMN` / `RENAME` without explicit user confirmation
