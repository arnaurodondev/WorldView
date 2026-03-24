# Standardization Remediation Guide — Implementation Steps

**Document**: Practical step-by-step instructions to fix audit violations
**Target audience**: Backend engineers implementing fixes
**Estimated total effort**: 6–8 hours for all Priority 1 fixes

---

## Table of Contents
1. [Fix Content-Ingestion (S4) Schema](#fix-1-content-ingestion-s4-schema)
2. [Refactor Portfolio (S1) Messaging](#fix-2-portfolio-s1-messaging)
3. [Refactor Market-Ingestion (S2) Messaging](#fix-3-market-ingestion-s2-messaging)
4. [Verification & Testing](#verification--testing)

---

## Fix 1: Content-Ingestion (S4) Schema

### Context
The `content.article.raw.v1.avsc` schema is missing required event envelope fields. This prevents proper event tracking and schema registry compliance.

### Steps

#### 1.1 Backup existing schema
```bash
cd services/content-ingestion
cp src/content_ingestion/infrastructure/messaging/schemas/content.article.raw.v1.avsc \
   src/content_ingestion/infrastructure/messaging/schemas/content.article.raw.v1.avsc.backup
```

#### 1.2 Update schema file
Replace the entire content of `src/content_ingestion/infrastructure/messaging/schemas/content.article.raw.v1.avsc` with:

```json
{
  "type": "record",
  "name": "ContentArticleRawV1",
  "namespace": "com.worldview",
  "doc": "Raw article fetched by S4 content-ingestion and stored in MinIO bronze.",
  "fields": [
    {
      "name": "event_id",
      "type": "string",
      "doc": "UUIDv7 event identifier"
    },
    {
      "name": "event_type",
      "type": "string",
      "default": "content.article.raw",
      "doc": "Event type identifier"
    },
    {
      "name": "schema_version",
      "type": "int",
      "default": 1,
      "doc": "Avro schema version"
    },
    {
      "name": "occurred_at",
      "type": "string",
      "doc": "ISO-8601 UTC timestamp when event occurred"
    },
    {
      "name": "correlation_id",
      "type": ["null", "string"],
      "default": null,
      "doc": "Unique ID for distributed tracing across services"
    },
    {
      "name": "causation_id",
      "type": ["null", "string"],
      "default": null,
      "doc": "ID of the event that caused this event"
    },
    {
      "name": "article_id",
      "type": "string",
      "doc": "UUIDv7 document identifier"
    },
    {
      "name": "source_type",
      "type": "string",
      "doc": "Source of article: eodhd | sec_edgar | finnhub | newsapi"
    },
    {
      "name": "url",
      "type": "string",
      "doc": "Source URL of the article"
    },
    {
      "name": "url_hash",
      "type": "string",
      "doc": "SHA-256 hex of the canonical URL (used for deduplication)"
    },
    {
      "name": "minio_key",
      "type": "string",
      "doc": "MinIO object key in bronze layer"
    },
    {
      "name": "fetched_at",
      "type": "string",
      "doc": "ISO-8601 UTC timestamp when article was fetched"
    },
    {
      "name": "byte_size",
      "type": "int",
      "doc": "Size of the article in bytes"
    },
    {
      "name": "published_at",
      "type": ["null", "string"],
      "default": null,
      "doc": "Source-reported publication date (ISO-8601 UTC); null if not available"
    },
    {
      "name": "is_backfill",
      "type": "boolean",
      "default": false,
      "doc": "True when produced during historical backfill run (vs. real-time ingestion)"
    }
  ]
}
```

#### 1.3 Verify JSON syntax
```bash
python3 -m json.tool src/content_ingestion/infrastructure/messaging/schemas/content.article.raw.v1.avsc > /dev/null
echo "✓ JSON syntax valid"
```

#### 1.4 Update producer code (if needed)
Check if the producer needs to populate the new envelope fields. Search for where this schema is used:

```bash
cd services/content-ingestion
grep -r "content.article.raw" src/ --include="*.py" | head -20
```

Look for the outbox event creation code. Typical pattern:
```python
# In application/use_cases/ingest_article.py or similar
outbox_event = OutboxEvent(
    event_id=common.ids.new_uuid7_str(),      # NEW: required
    event_type="content.article.raw",         # NEW: required
    schema_version=1,                         # NEW: required
    occurred_at=common.time.to_iso8601(common.time.utc_now()),  # NEW: required
    correlation_id=correlation_id,            # NEW: optional, from context
    causation_id=None,                        # NEW: optional
    # existing fields...
    article_id=article_id,
    source_type=source_type,
    # etc
)
```

#### 1.5 Run schema validation and tests
```bash
cd services/content-ingestion

# Run unit tests
make test

# If integration tests exist, run them
make test-integration

# Check linting
make lint
```

#### 1.6 Verify schema registry compatibility (if running locally)
```bash
# If you have Kafka schema registry running, check compatibility
# This is typically automated in CI/CD but good to verify locally if possible

# For now, the Schema Registry will validate on first producer use
# since it's configured for BACKWARD compatibility
```

**Estimated time**: 20 minutes

---

## Fix 2: Portfolio (S1) Messaging Structure Refactor

### Context
Portfolio has messaging code and consumers at the package root level, violating the hexagonal architecture. They must be moved under `infrastructure/messaging/`.

### Overview of Changes

**Current layout**:
```
src/portfolio/
├── messaging/              ← WRONG: should be infrastructure/messaging/
├── consumers/              ← WRONG: should be infrastructure/messaging/consumers/
├── infrastructure/
│   └── db/
```

**Target layout**:
```
src/portfolio/
├── infrastructure/
│   ├── messaging/          ← CORRECT
│   │   ├── outbox/
│   │   ├── consumers/
│   │   └── schemas/
│   └── db/
```

### Steps

#### 2.1 Create target directories
```bash
cd services/portfolio/src/portfolio/infrastructure/messaging

# Create subdirectories if they don't exist
mkdir -p outbox
mkdir -p consumers
mkdir -p schemas
```

#### 2.2 Move dispatcher files
```bash
cd services/portfolio/src/portfolio

# Move main dispatcher
mv messaging/dispatcher.py infrastructure/messaging/outbox/
mv messaging/dispatcher_main.py infrastructure/messaging/outbox/

# Move supporting files
mv messaging/mapper.py infrastructure/messaging/
mv messaging/outbox_mapper.py infrastructure/messaging/
mv messaging/serialization.py infrastructure/messaging/
mv messaging/topics.py infrastructure/messaging/
```

#### 2.3 Move schemas
```bash
cd services/portfolio/src/portfolio

# Move all schema files
mv messaging/schemas/* infrastructure/messaging/schemas/
rmdir messaging/schemas  # Remove empty directory
```

#### 2.4 Move consumer files
```bash
cd services/portfolio/src/portfolio

# Move consumers
mv consumers/instrument_consumer.py infrastructure/messaging/consumers/
rmdir consumers  # Remove empty directory
```

#### 2.5 Remove old messaging directory
```bash
cd services/portfolio/src/portfolio
rmdir messaging  # Should be empty now
```

#### 2.6 Update imports across portfolio service

**Create a script to help with import replacement**:
```bash
#!/bin/bash
# Replace imports in portfolio service
cd services/portfolio/src/portfolio

# Replace: from portfolio.messaging -> from portfolio.infrastructure.messaging
find . -name "*.py" -type f -exec sed -i '' \
  's/from portfolio\.messaging/from portfolio.infrastructure.messaging/g' {} \;

# Replace: import portfolio.messaging -> import portfolio.infrastructure.messaging
find . -name "*.py" -type f -exec sed -i '' \
  's/import portfolio\.messaging/import portfolio.infrastructure.messaging/g' {} \;

# Replace: from portfolio.consumers -> from portfolio.infrastructure.messaging.consumers
find . -name "*.py" -type f -exec sed -i '' \
  's/from portfolio\.consumers/from portfolio.infrastructure.messaging.consumers/g' {} \;

# Replace: import portfolio.consumers -> import portfolio.infrastructure.messaging.consumers
find . -name "*.py" -type f -exec sed -i '' \
  's/import portfolio\.consumers/import portfolio.infrastructure.messaging.consumers/g' {} \;
```

OR manually search for imports in these files:

**Key files likely to have imports**:
- `src/portfolio/app.py` — lifespan setup, dispatcher initialization
- `src/portfolio/infrastructure/db/session.py` — if it imports dispatcher
- `src/portfolio/application/use_cases/*.py` — if they emit events
- Any integration test files

**Example fix** (if found):
```python
# BEFORE
from portfolio.messaging.dispatcher import OutboxDispatcher
from portfolio.messaging.topics import EVENT_TOPIC_MAP
from portfolio.consumers.instrument_consumer import InstrumentConsumer

# AFTER
from portfolio.infrastructure.messaging.outbox.dispatcher import OutboxDispatcher
from portfolio.infrastructure.messaging.topics import EVENT_TOPIC_MAP
from portfolio.infrastructure.messaging.consumers.instrument_consumer import InstrumentConsumer
```

#### 2.7 Verify all imports are correct
```bash
cd services/portfolio

# Check for remaining old imports
grep -r "from portfolio\.messaging" src/ tests/ || echo "✓ No old messaging imports found"
grep -r "from portfolio\.consumers" src/ tests/ || echo "✓ No old consumer imports found"
grep -r "import portfolio\.messaging" src/ tests/ || echo "✓ No old messaging imports found"
grep -r "import portfolio\.consumers" src/ tests/ || echo "✓ No old consumer imports found"
```

#### 2.8 Update any config or initialization code
Check `src/portfolio/app.py` and any initialization code for hardcoded module paths:

```python
# BEFORE
from portfolio.messaging.dispatcher import OutboxDispatcher

# AFTER
from portfolio.infrastructure.messaging.outbox.dispatcher import OutboxDispatcher
```

#### 2.9 Update test imports
```bash
cd services/portfolio

# Check tests for old imports
grep -r "portfolio\.messaging\|portfolio\.consumers" tests/ --include="*.py" | head -10

# Update test files similarly
find tests/ -name "*.py" -type f -exec sed -i '' \
  's/from portfolio\.messaging/from portfolio.infrastructure.messaging/g' {} \;
find tests/ -name "*.py" -type f -exec sed -i '' \
  's/import portfolio\.messaging/import portfolio.infrastructure.messaging/g' {} \;
find tests/ -name "*.py" -type f -exec sed -i '' \
  's/from portfolio\.consumers/from portfolio.infrastructure.messaging.consumers/g' {} \;
```

#### 2.10 Verify __init__.py files
Ensure proper __init__.py files exist in new directories:

```bash
cd services/portfolio/src/portfolio/infrastructure/messaging

# Create empty __init__.py if needed
touch __init__.py
touch outbox/__init__.py
touch consumers/__init__.py

# Add content if necessary (usually empty for namespace packages)
```

#### 2.11 Run tests
```bash
cd services/portfolio

# Run full test suite
make test

# Run linting
make lint

# Run type checking
make mypy
```

**Expected result**: All tests pass, no import errors

#### 2.12 Update documentation
Update `docs/services/portfolio.md` if it references the old structure:

```markdown
### Messaging

The outbox dispatcher and event consumers are located in:
- Dispatcher: `src/portfolio/infrastructure/messaging/outbox/dispatcher.py` ✓
- Consumers: `src/portfolio/infrastructure/messaging/consumers/` ✓
- Schemas: `src/portfolio/infrastructure/messaging/schemas/` ✓
```

**Estimated time**: 1.5–2 hours (depending on number of imports)

---

## Fix 3: Market-Ingestion (S2) Messaging Structure Refactor

### Context
Market-Ingestion has messaging code at package root and scheduler/worker modules outside canonical DDD. Requires more complex refactoring.

### Overview of Changes

**Current layout**:
```
src/market_ingestion/
├── messaging/              ← WRONG: at root
├── scheduler/              ← WRONG: should be part of application
├── worker/                 ← WRONG: should be part of infrastructure
├── infrastructure/
│   ├── messaging/          ← INCOMPLETE
│   ├── db/
│   └── adapters/
```

**Target layout**:
```
src/market_ingestion/
├── infrastructure/
│   ├── messaging/          ← CORRECT, merged from root
│   │   ├── outbox/
│   │   └── schemas/
│   ├── db/
│   ├── adapters/
│   └── workers/            ← MOVED from root
├── application/
│   ├── schedulers/         ← MOVED from root, refactored
│   └── use_cases/
├── domain/
└── api/
```

### Steps

#### 3.1 Backup current structure
```bash
cd services/market-ingestion
git status  # Ensure you're on a clean branch
```

#### 3.2 Move messaging code from root
```bash
cd services/market-ingestion/src/market_ingestion

# Move dispatcher from root messaging to infrastructure
mv messaging/dispatcher_main.py infrastructure/messaging/outbox/
rmdir messaging/schemas 2>/dev/null || true  # Remove if exists
rmdir messaging 2>/dev/null || true  # Remove root messaging directory
```

#### 3.3 Evaluate scheduler and worker modules

**First, understand what these modules do**:
```bash
cd services/market-ingestion/src/market_ingestion

# Check scheduler structure
ls -la scheduler/
# Output should show: Python modules related to scheduling logic

# Check worker structure
ls -la worker/
# Output should show: Python modules related to worker execution
```

**Typical refactoring approach**:
- **Scheduler logic** (policy, timing, etc.) → `application/schedulers/`
- **Worker execution** (runners, handlers, async dispatch) → `infrastructure/workers/`

#### 3.4 Create target directories
```bash
cd services/market-ingestion/src/market_ingestion

# Create application schedulers directory
mkdir -p application/schedulers

# Create infrastructure workers directory
mkdir -p infrastructure/workers
```

#### 3.5 Move scheduler to application
```bash
cd services/market-ingestion/src/market_ingestion

# Copy scheduler module to application
cp -r scheduler/* application/schedulers/

# Update __init__.py if needed
touch application/schedulers/__init__.py
```

#### 3.6 Move worker to infrastructure
```bash
cd services/market-ingestion/src/market_ingestion

# Copy worker module to infrastructure
cp -r worker/* infrastructure/workers/

# Update __init__.py if needed
touch infrastructure/workers/__init__.py
```

#### 3.7 Update imports throughout service

**Change patterns**:
```python
# BEFORE
from market_ingestion.scheduler import ...
from market_ingestion.worker import ...
from market_ingestion.messaging import ...

# AFTER
from market_ingestion.application.schedulers import ...
from market_ingestion.infrastructure.workers import ...
from market_ingestion.infrastructure.messaging import ...
```

**Auto-replace script**:
```bash
cd services/market-ingestion/src

# Scheduler imports
find . -name "*.py" -type f -exec sed -i '' \
  's/from market_ingestion\.scheduler/from market_ingestion.application.schedulers/g' {} \;

# Worker imports
find . -name "*.py" -type f -exec sed -i '' \
  's/from market_ingestion\.worker/from market_ingestion.infrastructure.workers/g' {} \;

# Messaging imports
find . -name "*.py" -type f -exec sed -i '' \
  's/from market_ingestion\.messaging/from market_ingestion.infrastructure.messaging/g' {} \;
```

#### 3.8 Verify all imports
```bash
cd services/market-ingestion

# Check for remaining old imports
grep -r "from market_ingestion\.scheduler\|from market_ingestion\.worker\|from market_ingestion\.messaging" src/ tests/ --include="*.py" | wc -l
# Should output: 0

# If non-zero, show what wasn't updated
grep -r "from market_ingestion\.scheduler\|from market_ingestion\.worker\|from market_ingestion\.messaging" src/ tests/ --include="*.py" || echo "✓ All imports updated"
```

#### 3.9 Delete root-level directories
```bash
cd services/market-ingestion/src/market_ingestion

# Remove old directories (NOW that code is moved)
rm -rf scheduler/
rm -rf worker/
# messaging/ should already be removed or only have __init__.py

# Verify
ls -la | grep -E "^d.*scheduler|^d.*worker|^d.*messaging"
# Should output nothing if cleanup successful
```

#### 3.10 Run linting to catch import errors
```bash
cd services/market-ingestion

# Check for import errors
make lint 2>&1 | grep -i "import\|module" | head -20

# Run mypy to catch unresolved imports
make mypy 2>&1 | grep -i "import\|module" | head -20
```

#### 3.11 Run full test suite
```bash
cd services/market-ingestion

# Run all tests
make test

# If test failures, they likely point to:
# 1. Remaining unupdated imports
# 2. Circular import issues (watch for these!)
# 3. Module-level code that assumed old structure
```

#### 3.12 Handle any circular imports
If you see circular import errors:
- Move initialization code from top-level `__init__.py` to later binding
- Use `TYPE_CHECKING` import guards
- Defer imports to function bodies if necessary

Example fix for circular imports:
```python
# BEFORE (circular)
from market_ingestion.infrastructure.workers import ScheduledWorker
from market_ingestion.application.schedulers import Scheduler

class Scheduler:
    def __init__(self, worker: ScheduledWorker):  # Circular!
        self.worker = worker

# AFTER (deferred)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_ingestion.infrastructure.workers import ScheduledWorker

class Scheduler:
    def __init__(self, worker: "ScheduledWorker"):
        self.worker = worker
```

#### 3.13 Update documentation
Update `docs/services/market-ingestion.md`:

```markdown
### Architecture

Market-Ingestion follows hexagonal architecture:

- **Application**: `src/market_ingestion/application/`
  - Use cases: polling, task execution, ingestion triggering
  - Schedulers: task scheduling policies (moved from root scheduling module)
- **Infrastructure**: `src/market_ingestion/infrastructure/`
  - Messaging: `messaging/` with outbox and schema
  - Workers: worker execution strategies and runners (moved from root worker module)
  - Database: repositories and models
```

**Estimated time**: 2–3 hours (complex refactor with potential circular import issues)

---

## Verification & Testing

### Step 1: Full Test Suite

Run all tests for affected services:
```bash
cd services/portfolio
make test  # Should pass with 100% success rate

cd services/market-ingestion
make test  # Should pass with 100% success rate

cd services/content-ingestion
make test  # Should pass with 100% success rate
```

### Step 2: Linting & Type Checking

```bash
cd services/portfolio
make lint
make mypy

cd services/market-ingestion
make lint
make mypy

cd services/content-ingestion
make lint
make mypy
```

### Step 3: Integration Testing (if available)

```bash
# Start infrastructure (if tests require it)
docker compose -f infra/compose/docker-compose.yml --profile infra up -d

# Run integration tests
cd services/portfolio
make test-integration

cd services/market-ingestion
make test-integration

# Cleanup
docker compose -f infra/compose/docker-compose.yml --profile infra down
```

### Step 4: Schema Validation

Verify Avro schemas are valid:
```bash
# For Content-Ingestion
python3 -m json.tool services/content-ingestion/src/content_ingestion/infrastructure/messaging/schemas/content.article.raw.v1.avsc

# For Portfolio (after refactor, if schema files moved)
python3 -m json.tool services/portfolio/src/portfolio/infrastructure/messaging/schemas/*.avsc | head -5

# For Market-Ingestion
python3 -m json.tool services/market-ingestion/src/market_ingestion/infrastructure/messaging/schemas/*.avsc | head -5
```

### Step 5: Verify Directory Structure

```bash
# Check Portfolio structure is correct
ls -la services/portfolio/src/portfolio/infrastructure/messaging/
# Should show: __init__.py, outbox/, consumers/, schemas/

# Check Market-Ingestion structure is correct
ls -la services/market-ingestion/src/market_ingestion/infrastructure/
# Should NOT have messaging/ at root
ls -la services/market-ingestion/src/market_ingestion/application/
# Should show: schedulers/

# Check Content-Ingestion schema
ls -la services/content-ingestion/src/content_ingestion/infrastructure/messaging/schemas/
# Should show: content.article.raw.v1.avsc
```

### Step 6: Git Commit and PR

```bash
# Verify all changes
git status

# Stage changes
git add services/portfolio/
git add services/market-ingestion/
git add services/content-ingestion/
git add docs/STANDARDIZATION_AUDIT_2025.md

# Commit with clear message
git commit -m "fix: standardize messaging structure and event schemas

- Move Portfolio messaging/consumers to infrastructure/messaging
- Move Market-Ingestion messaging to infrastructure/messaging
- Move Market-Ingestion scheduler/worker to application/infrastructure
- Update Content-Ingestion event schema to include envelope fields
- Update all imports across affected services
- All tests passing"

# Create PR for review
git push origin your-branch-name
```

---

## Rollback Plan

If any fix encounters unforeseen issues:

```bash
# For Content-Ingestion schema only:
cd services/content-ingestion
cp src/content_ingestion/infrastructure/messaging/schemas/content.article.raw.v1.avsc.backup \
   src/content_ingestion/infrastructure/messaging/schemas/content.article.raw.v1.avsc

# For full refactors, use git to revert:
git reset --hard <commit-before-refactor>
```

---

## Time Estimates (Reality Check)

| Fix | Estimated | Range | Notes |
|-----|-----------|-------|-------|
| Content-Ingestion Schema | 20 min | 15–30 min | Schema-only change; simple |
| Portfolio Refactor | 1.5–2 hrs | 1–2.5 hrs | Depends on number of imports; high confidence |
| Market-Ingestion Refactor | 2–3 hrs | 2–4 hrs | Complex; circular imports possible; needs careful handling |
| Testing & Verification | 30 min | 20–45 min | All tests must pass |
| **Total** | **4.5–5.5 hrs** | **4–7 hrs** | Comfortable assumption for two engineers |

---

**Ready to implement?** Start with Fix 1 (Content-Ingestion schema) — it's the quickest and builds confidence for the more complex refactors.
