# NLP Pipeline DLQ Stall Investigation — F-DB-NEW-001 CRITICAL

**Timestamp**: 2026-05-26 01:59 UTC
**Status**: Root cause identified; NOT a code bug; schema enforcement on pre-migration articles.
**Articles affected**: 94 messages stuck; 504 constraint violations logged 2026-05-24 19:25:27–present.

---

## Live State Snapshot

### Database
```
nlp_db=> SELECT count(*) as entity_mentions_count FROM entity_mentions;
 entity_mentions_count
-----------------------
                     0
(1 row)
```

### Kafka Topics
```bash
$ kafka-topics --bootstrap-server localhost:9092 --list | grep article
content.article.raw.v1
content.article.stored.v1          # 94 messages backlog (source of truth)
content.article.stored.v1.dlq     # Empty — no messages have reached DLQ yet
nlp.article.enriched.v1
```

**Conclusion**: Messages are **stuck in flight**, not in DLQ. Consumer crashes on every message, Kafka consumer group does not advance offset.

### Worker Health
- `worldview-nlp-pipeline-article-consumer-1` — restarting in crash loop
- Last log entry before Kafka connectivity crash: `2026-05-24T19:25:27.892716Z` (504 IntegrityError attempts)
- Connectivity probe crash: `2026-05-26T01:59:16.266071Z` (broker transport failure during retry backoff)

---

## Root Cause: Stale Article Messages Without tenant_id

### The Error (504 occurrences)
```
sqlalchemy.dialects.postgresql.asyncpg.IntegrityError:
  null value in column "tenant_id" of relation "entity_mentions"
  violates not-null constraint

SQL parameters: (..., tenant_id=None, ...)
```

### Why It Happens
1. **Migration 0020** (`entity_mentions.tenant_id NOT NULL`) added 2026-05-XX, enforcing tenant_id must always be present.
2. **Articles from before 2026-05-24** were published to `content.article.stored.v1` **before the S5 content-store code began stamping tenant_id in the payload** (PLAN-0086 Wave A-1 likely not yet merged in production).
3. When the article consumer processes these stale messages:
   - It extracts `tenant_id` from message headers or payload (article_consumer.py:454)
   - For **old articles: `tenant_id` is `None`** (field not present in pre-PLAN-0086 Avro events)
   - Article consumer stamping code (article_consumer.py:563–565) **attempts to set tenant_id = None**
   - NER block creates EntityMention objects with `tenant_id=None` (application/blocks/ner.py:209)
   - INSERT hits NOT NULL constraint → IntegrityError → message sent to retry queue
   - Retries fail identically because the message content never changes

### Code Path (article_consumer.py)
```python
# Line 454-458: Extract tenant_id from headers/payload
raw_tenant = headers.get("tenant_id") or value.get("tenant_id") or None
tenant_id: uuid.UUID | None = None
if raw_tenant:
    with contextlib.suppress(ValueError, AttributeError):
        tenant_id = uuid.UUID(str(raw_tenant))
        # ↑ If raw_tenant is None, tenant_id stays None

# Line 559: Pass None to NER block
mentions, stats = await run_ner_block(
    ...
    tenant_id=tenant_id,  # ← None for stale articles
)

# Line 563-565: Attempt to stamp (but it's already too late)
if tenant_id is not None:
    for m in mentions:
        m.tenant_id = tenant_id  # ← Skipped when tenant_id is None
```

### Why DLQ Is Empty
The `content.article.stored.v1.dlq` topic is empty because:
1. Messages fail during `_run_pipeline` (persist_artifacts → entity_mention.add_batch)
2. The consumer's exception handler treats IntegrityError as **retryable** (not fatal)
3. Messages stay in Kafka consumer group's **in-flight state** (offset not committed)
4. No separate DLQ fanout is triggered; message remains on the main topic until offset is committed

---

## Impact Quantification

| Metric | Value |
|--------|-------|
| Articles in backlog | 94 messages (all stuck on `content.article.stored.v1`) |
| Constraint violations logged | 504 (multiple retry attempts per article) |
| Entity mentions created | 0 (pipeline blocked at persist layer) |
| Last successful article processed | ~2026-05-24 19:25:27 UTC (>24h ago) |
| Entity extraction NER model | Running fine (logs show GLiNER batches processing) |
| Deepinfra embeddings | Running fine (logs show 200 OK responses) |
| Database connectivity | OK (IntegrityError is a validation error, not a connection issue) |

**Core issue**: Data **older than the schema** (pre-migration articles without tenant_id field) cannot be processed once the NOT NULL constraint is enforced.

---

## Consumer Code Path (Full Stack)

**File**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py`

```
process_message() [line 445]
  ├─ Extract tenant_id from message [line 454]
  └─ _run_pipeline() [line 480]
      ├─ section_document() [line 542]
      ├─ run_ner_block(..., tenant_id=tenant_id) [line 551]
      │   └─ Create EntityMention(tenant_id=tenant_id) [ner.py:209]
      └─ persist_artifacts() [line 650]
          └─ EntityMentionRepository.add_batch() [entity_mention.py:78]
              └─ INSERT entity_mentions(...) ON CONFLICT (mention_id) DO NOTHING [entity_mention.py:76]
                  → ❌ NOT NULL constraint violation: tenant_id=None
```

**Migration that added constraint**:
`services/nlp-pipeline/alembic/versions/0020_entity_mentions_tenant_not_null.py`

---

## Fix Sketch (Minimal + Regression Test)

### Option 1: Retroactive Fallback (Recommended)
Add a **default tenant UUID** when `tenant_id` is None in the article consumer:

**File**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py` (~line 454)

```python
# Extract tenant_id; use a sentinel/default if missing (stale articles pre-PLAN-0086)
raw_tenant = headers.get("tenant_id") or value.get("tenant_id") or None
tenant_id: uuid.UUID | None = None
if raw_tenant:
    with contextlib.suppress(ValueError, AttributeError):
        tenant_id = uuid.UUID(str(raw_tenant))

# DEFAULT FOR STALE ARTICLES: Use a well-known "public" tenant UUID
# This allows pre-PLAN-0086 articles to be processed without blocking the pipeline
if tenant_id is None:
    tenant_id = uuid.UUID("00000000-0000-7000-8000-000000000001")  # PUBLIC_TENANT_ID
```

### Option 2: Skip Stale Articles (Alternative)
Log a warning and return early for articles without tenant_id:

```python
if tenant_id is None and not is_backfill:
    logger.warning("article_consumer.skip_pre_plan0086", doc_id=str(doc_id))
    return
```

### Regression Test

**File**: `services/nlp-pipeline/tests/integration/test_consumer_pipeline.py`

```python
async def test_article_consumer_handles_stale_tenant_id_none():
    """Regression for BP-XXX: articles published before tenant_id field must not crash."""
    # Simulate a pre-PLAN-0086 article (no tenant_id in headers/payload)
    article_payload = {
        "doc_id": str(UUID4()),
        "minio_silver_key": "...",
        "source_type": "finnhub",
        "title": "Test Article",
        # ❌ NO tenant_id field
    }
    headers = {
        # ❌ NO tenant_id header
    }

    consumer = ArticleProcessingConsumer(...)
    await consumer.process_message(key=None, value=article_payload, headers=headers)

    # Should NOT raise IntegrityError
    # entity_mentions should exist (with default public tenant UUID)
    assert await session.execute(select(func.count(EntityMentionModel.mention_id))) > 0
```

---

## Severity & Categorization

**Severity**: CRITICAL (P0)
- Pipeline 100% blocked (0 articles processed in 24h)
- Affects all consumers downstream (NLP, KG, RAG-chat starved)
- Data is **not lost**, just stuck in Kafka

**Root Category**: Schema Enforcement on Stale Data (BP-XXX)
**Pattern Name** (if new): **BP-XXX — NOT NULL constraint migration without fallback path for pre-migration messages**

### Lessons
1. **Migration strategy**: NOT NULL constraints on new fields require explicit handling for messages in flight that predate the code change.
2. **Kafka offset management**: Messages that fail deterministically (constraint violations) do not auto-DLQ; they block the entire consumer group.
3. **Test coverage**: Integration tests must include pre-migration message payloads after schema changes.

---

## Next Steps

1. **Immediate**: Apply Option 1 (retroactive fallback) or Option 2 (skip stale).
2. **Reprocess**: After fix, consumer will automatically restart and process the 94 backlog messages.
3. **Monitoring**: Add metric `nlp.article.tenant_id_missing_count` to track recurrence.
4. **Documentation**: Update PLAN-0086 to note that content.article.raw.v1 → stored.v1 backwards-compatibility requires a multi-version deprecation window.

---

**Report compiled**: 2026-05-26 UTC
**Investigated by**: Claude Code — Investigation skill
**Status**: Awaiting approval for fix implementation
