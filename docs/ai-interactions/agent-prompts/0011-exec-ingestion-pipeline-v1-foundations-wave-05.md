# Execution Prompt 0011 — Ingestion Pipeline v1 Foundations · Wave 05 (Final)

## Context (read first)

- **Planning response**: `docs/ai-interactions/agent-responses/0011-response-20260322-ingestion-pipeline-v1-foundations.md`
- **Authoritative spec**: `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md` §7, §12.5

## Assigned agent profile(s)

- `.claude/agents/data-platform-engineer.md`

## Mandatory pre-read

1. `AGENTS.md`
2. `CLAUDE.md`
3. `RULES.md`
4. `docs/ai-interactions/agent-responses/0011-response-20260322-ingestion-pipeline-v1-foundations.md` — task specs for T-F-012, T-F-013
5. `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md` §7 (Kafka topic definitions + partition counts + retention), §12.5 (topic configuration)
6. `infra/kafka/init/create-topics.sh` (current file — read before editing)
7. `infra/kafka/init/register-schemas.py` (verify FULL compat step from Wave 01 is present)
8. `libs/contracts/src/contracts/__init__.py` (current exports — read before editing)
9. `libs/contracts/src/contracts/versions.py` (current version constants)
10. `infra/kafka/schemas/content.article.raw.v1.avsc` (field source for CanonicalRawArticleEvent)
11. `infra/kafka/schemas/content.article.stored.v1.avsc` (field source for CanonicalStoredArticleEvent)
12. `infra/kafka/schemas/nlp.article.enriched.v1.avsc` (field source for CanonicalEnrichedArticleEvent)
13. `infra/kafka/schemas/nlp.signal.detected.v1.avsc` (field source for CanonicalSignalEvent)
14. `docs/libs/contracts.md` (update target for T-F-013)

## Objective

Execute two tasks in parallel: update the Kafka topic init config to match PRD §7 exactly (T-F-012) and add five new canonical event dataclasses to `libs/contracts` (T-F-013). Both are independent of each other and can proceed concurrently.

**This is the final wave of Prompt 0011.** All prior waves must be committed before Wave 05 begins. This wave closes out M3 (Avro Schemas + Kafka Topics + Contracts complete) and unblocks Prompt 0016 (S4/S5 implementation) and Prompt 0017 (S6/S7/S10 implementation).

## Task scope for this wave

### Parallel group — both tasks are independent

| Task | What | Files touched |
|------|------|---------------|
| **T-F-012** | Update `create-topics.sh`: fix 5 partition counts, add 5 new topics, configure `entity.dirtied.v1` compaction | `infra/kafka/init/create-topics.sh` |
| **T-F-013** | Add 5 canonical event dataclasses to `libs/contracts`: `CanonicalRawArticleEvent`, `CanonicalStoredArticleEvent`, `CanonicalEnrichedArticleEvent`, `CanonicalSignalEvent`, `CanonicalWatchlistEvent` | `libs/contracts/src/contracts/canonical/ingestion.py` (new), `__init__.py`, `versions.py`, tests, `docs/libs/contracts.md` |

## Implementation instructions

### T-F-012 — Kafka topic init config update

#### Step 1 — Read the current file

Read `infra/kafka/init/create-topics.sh` before making any edit. Note the exact variable names (`KAFKA_TOPICS_CMD`, `BOOTSTRAP`, topic array structure) to preserve the existing script style.

#### Step 2 — Correct existing partition counts

The following topics have wrong partition counts. Find each topic entry and update the partition count to match PRD §7:

| Topic | Current partitions | PRD §7 required |
|-------|--------------------|-----------------|
| `content.article.raw.v1` | 3 | **12** |
| `content.article.stored.v1` | 6 | **12** |
| `nlp.article.enriched.v1` | 6 | **12** |
| `nlp.signal.detected.v1` | 3 | **24** |
| `portfolio.watchlist.updated.v1` | 3 | **12** |

Do NOT change any other topic's partition count. Do NOT change replication-factor settings.

#### Step 3 — Add 4 new time-retention topics

Add the following topics to the standard creation loop (same pattern as existing topics):

```bash
# New time-retention topics (add alongside existing topics)
graph.state.changed.v1        partitions=12   replication-factor=1
intelligence.contradiction.v1 partitions=12   replication-factor=1
relation.type.proposed.v1     partitions=4    replication-factor=1
alert.delivered.v1            partitions=12   replication-factor=1
```

All 4 use `--if-not-exists` for idempotency.

#### Step 4 — Add `entity.dirtied.v1` as a compacted topic

This topic requires special creation outside the standard loop because it needs `cleanup.policy=compact`. Add it as a separate, clearly commented block:

```bash
# ── Compacted topic (log compaction, NOT time-retention) ─────────────────────
echo "Creating compacted topic: entity.dirtied.v1"
"$KAFKA_TOPICS_CMD" \
    --bootstrap-server "$BOOTSTRAP" \
    --create \
    --if-not-exists \
    --topic entity.dirtied.v1 \
    --partitions 24 \
    --replication-factor 1 \
    --config cleanup.policy=compact \
    --config min.cleanable.dirty.ratio=0.01 \
    --config segment.ms=3600000
```

Compaction semantics: after compaction runs, only the latest message per `entity_id` (the Kafka key) is retained. This is the correct behavior — S7 async workers treat each message as "refresh entity X", not a historical sequence. Document this in a comment in the script.

#### Step 5 — Add custom retention configs

After the topic creation block, add `--alter` commands for topics with non-default retention. Use separate `echo` statements for readability:

```bash
# ── Custom retention configuration ────────────────────────────────────────────
# 14-day retention: signal and graph change topics (operational data, high volume)
echo "Setting 14-day retention on nlp.signal.detected.v1"
"$KAFKA_TOPICS_CMD" --bootstrap-server "$BOOTSTRAP" --alter \
    --topic nlp.signal.detected.v1 \
    --config retention.ms=1209600000

echo "Setting 14-day retention on graph.state.changed.v1"
"$KAFKA_TOPICS_CMD" --bootstrap-server "$BOOTSTRAP" --alter \
    --topic graph.state.changed.v1 \
    --config retention.ms=1209600000

# 30-day retention: contradiction and relation type (lower volume; longer audit window)
echo "Setting 30-day retention on intelligence.contradiction.v1"
"$KAFKA_TOPICS_CMD" --bootstrap-server "$BOOTSTRAP" --alter \
    --topic intelligence.contradiction.v1 \
    --config retention.ms=2592000000

echo "Setting 30-day retention on relation.type.proposed.v1"
"$KAFKA_TOPICS_CMD" --bootstrap-server "$BOOTSTRAP" --alter \
    --topic relation.type.proposed.v1 \
    --config retention.ms=2592000000
```

Note: `relation.type.proposed.v1` uses FULL Schema Registry compatibility (set by `register-schemas.py` in Wave 01). The topic retention is independent of schema compatibility — both settings are required.

#### Step 6 — Final verification block

Add a final block that lists all topics after creation:

```bash
# ── Verification ──────────────────────────────────────────────────────────────
echo "All topics created. Current topic list:"
"$KAFKA_TOPICS_CMD" --bootstrap-server "$BOOTSTRAP" --list
```

**Complete topic inventory after T-F-012** (10 topics total):

| Topic | Partitions | Type | Retention |
|-------|-----------|------|-----------|
| `content.article.raw.v1` | 12 | time-retention | default (7d) |
| `content.article.stored.v1` | 12 | time-retention | default |
| `nlp.article.enriched.v1` | 12 | time-retention | default |
| `nlp.signal.detected.v1` | 24 | time-retention | 14d |
| `portfolio.watchlist.updated.v1` | 12 | time-retention | default |
| `graph.state.changed.v1` | 12 | time-retention | 14d |
| `intelligence.contradiction.v1` | 12 | time-retention | 30d |
| `relation.type.proposed.v1` | 4 | time-retention | 30d |
| `alert.delivered.v1` | 12 | time-retention | default |
| `entity.dirtied.v1` | 24 | **compacted** | N/A (compaction) |

**Validation gate** (run before marking T-F-012 done):
```bash
# Idempotency check — script must be valid bash
bash -n infra/kafka/init/create-topics.sh
# Must exit 0

# Verify topic count
grep -c "\\-\\-topic " infra/kafka/init/create-topics.sh
# Must be >= 10 (one --topic flag per topic; some topics have multiple for --alter)

# Verify compacted topic config
grep "cleanup.policy=compact" infra/kafka/init/create-topics.sh
# Must return a result

# Verify entity.dirtied.v1 partition count
grep -A5 "entity.dirtied.v1" infra/kafka/init/create-topics.sh | grep "partitions 24"
# Must return a result

# Verify nlp.signal.detected.v1 partition count fix
grep -A3 "nlp.signal.detected.v1" infra/kafka/init/create-topics.sh | grep "24"
# Must return a result (for --create --partitions 24)

# Verify content.article.raw.v1 partition count fix
grep -A3 "content.article.raw.v1" infra/kafka/init/create-topics.sh | grep "12"
# Must return a result
```

---

### T-F-013 — `libs/contracts` ingestion canonical event models

#### Step 1 — Read the existing contracts library

Before writing any code:
1. Read `libs/contracts/src/contracts/__init__.py` — note the existing exports (`CanonicalOHLCVBar`, `CanonicalArticle`, etc.) and the `from_dict`/`to_dict` pattern.
2. Read `libs/contracts/src/contracts/versions.py` — note the existing version constants.
3. Read `libs/contracts/src/contracts/canonical/` directory — identify the existing module structure (likely `market.py`, `content.py`, or similar).

Do not invent new patterns — match the existing `from_dict`/`to_dict` frozen dataclass pattern exactly.

#### Step 2 — Create `libs/contracts/src/contracts/canonical/ingestion.py`

Five new frozen dataclasses, each mirroring its corresponding Avro schema:

```python
"""Canonical event dataclasses for the ingestion pipeline.

These models mirror the Avro schemas in infra/kafka/schemas/ and provide
a typed Python interface for producers and consumers. Each model implements
from_dict() and to_dict() for Avro payload interop.

Field names match the Avro schema field names exactly. Do NOT rename fields
to match Python conventions — parity with the schema is the contract.
"""
from __future__ import annotations

import dataclasses
from typing import Optional


@dataclasses.dataclass(frozen=True)
class CanonicalRawArticleEvent:
    """Mirrors content.article.raw.v1.avsc — produced by S4, consumed by S5."""

    event_id: str
    event_type: str  # always "content.article.raw"
    schema_version: int
    occurred_at: str  # ISO-8601 string; TIMESTAMPTZ at the DB level
    url_hash: str
    source_id: str
    source_domain: str
    url: str
    minio_bucket: str
    minio_key: str
    title: Optional[str] = None
    content_type: str = "text/html"
    correlation_id: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "CanonicalRawArticleEvent":
        return cls(
            event_id=d["event_id"],
            event_type=d["event_type"],
            schema_version=d["schema_version"],
            occurred_at=d["occurred_at"],
            url_hash=d["url_hash"],
            source_id=d["source_id"],
            source_domain=d["source_domain"],
            url=d["url"],
            minio_bucket=d["minio_bucket"],
            minio_key=d["minio_key"],
            title=d.get("title"),
            content_type=d.get("content_type", "text/html"),
            correlation_id=d.get("correlation_id"),
        )

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at,
            "url_hash": self.url_hash,
            "source_id": self.source_id,
            "source_domain": self.source_domain,
            "url": self.url,
            "minio_bucket": self.minio_bucket,
            "minio_key": self.minio_key,
            "title": self.title,
            "content_type": self.content_type,
            "correlation_id": self.correlation_id,
        }


@dataclasses.dataclass(frozen=True)
class CanonicalStoredArticleEvent:
    """Mirrors content.article.stored.v1.avsc — produced by S5, consumed by S6."""

    event_id: str
    event_type: str  # always "content.article.stored"
    schema_version: int
    occurred_at: str
    article_id: str  # maps to doc_id in content_store_db; field name preserved for schema compat
    source_domain: str
    title: str
    url: str
    language: str = "en"
    word_count: int = 0
    is_duplicate: bool = False
    duplicate_of: Optional[str] = None
    published_at: Optional[str] = None
    correlation_id: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "CanonicalStoredArticleEvent":
        return cls(
            event_id=d["event_id"],
            event_type=d["event_type"],
            schema_version=d["schema_version"],
            occurred_at=d["occurred_at"],
            article_id=d["article_id"],
            source_domain=d["source_domain"],
            title=d["title"],
            url=d["url"],
            language=d.get("language", "en"),
            word_count=d.get("word_count", 0),
            is_duplicate=d.get("is_duplicate", False),
            duplicate_of=d.get("duplicate_of"),
            published_at=d.get("published_at"),
            correlation_id=d.get("correlation_id"),
        )

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at,
            "article_id": self.article_id,
            "source_domain": self.source_domain,
            "title": self.title,
            "url": self.url,
            "language": self.language,
            "word_count": self.word_count,
            "is_duplicate": self.is_duplicate,
            "duplicate_of": self.duplicate_of,
            "published_at": self.published_at,
            "correlation_id": self.correlation_id,
        }


@dataclasses.dataclass(frozen=True)
class CanonicalEnrichedArticleEvent:
    """Mirrors nlp.article.enriched.v1.avsc — produced by S6, consumed by S7.

    Note: embedding_model field default is "all-MiniLM-L6-v2" in the schema for
    backward compatibility. The active model in production is bge-large-en-v1.5.
    Do NOT change the schema default — this is a compatibility artifact.
    Always check the actual embedding_model value in the event payload.
    """

    event_id: str
    event_type: str  # always "nlp.article.enriched"
    schema_version: int
    occurred_at: str
    article_id: str  # logical FK to content_store_db documents; field name preserved
    embedding_model: str = "all-MiniLM-L6-v2"  # backward-compat default; actual = bge-large-en-v1.5
    entity_count: int = 0
    event_count: int = 0
    sentiment_label: Optional[str] = None
    sentiment_score: Optional[float] = None
    topic_cluster_id: Optional[str] = None
    correlation_id: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "CanonicalEnrichedArticleEvent":
        return cls(
            event_id=d["event_id"],
            event_type=d["event_type"],
            schema_version=d["schema_version"],
            occurred_at=d["occurred_at"],
            article_id=d["article_id"],
            embedding_model=d.get("embedding_model", "all-MiniLM-L6-v2"),
            entity_count=d.get("entity_count", 0),
            event_count=d.get("event_count", 0),
            sentiment_label=d.get("sentiment_label"),
            sentiment_score=d.get("sentiment_score"),
            topic_cluster_id=d.get("topic_cluster_id"),
            correlation_id=d.get("correlation_id"),
        )

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at,
            "article_id": self.article_id,
            "embedding_model": self.embedding_model,
            "entity_count": self.entity_count,
            "event_count": self.event_count,
            "sentiment_label": self.sentiment_label,
            "sentiment_score": self.sentiment_score,
            "topic_cluster_id": self.topic_cluster_id,
            "correlation_id": self.correlation_id,
        }


@dataclasses.dataclass(frozen=True)
class CanonicalSignalEvent:
    """Mirrors nlp.signal.detected.v1.avsc — produced by S6, consumed by S10."""

    event_id: str
    event_type: str  # always "nlp.signal.detected"
    schema_version: int
    occurred_at: str
    entity_id: str
    signal_type: str
    title: str
    severity: int = 1
    source_article_ids: tuple[str, ...] = ()  # tuple for frozen immutability; from_dict converts list
    details: Optional[str] = None  # JSON-encoded detail payload
    correlation_id: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "CanonicalSignalEvent":
        return cls(
            event_id=d["event_id"],
            event_type=d["event_type"],
            schema_version=d["schema_version"],
            occurred_at=d["occurred_at"],
            entity_id=d["entity_id"],
            signal_type=d["signal_type"],
            title=d["title"],
            severity=d.get("severity", 1),
            source_article_ids=tuple(d.get("source_article_ids", [])),
            details=d.get("details"),
            correlation_id=d.get("correlation_id"),
        )

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at,
            "entity_id": self.entity_id,
            "signal_type": self.signal_type,
            "title": self.title,
            "severity": self.severity,
            "source_article_ids": list(self.source_article_ids),  # Avro array requires list
            "details": self.details,
            "correlation_id": self.correlation_id,
        }


@dataclasses.dataclass(frozen=True)
class CanonicalWatchlistEvent:
    """Mirrors portfolio.watchlist.updated.v1.avsc envelope — produced by S1, consumed by S10.

    The event_type field discriminates the two event subtypes:
      - "watchlist.item_added"   — entity added to a watchlist
      - "watchlist.item_deleted" — entity removed from a watchlist (PRD §1.5 rule 5)

    Never construct this with event_type = "watchlist.item_removed" — that string was
    deprecated in Wave 01 (T-F-001) and is a bug if it appears.
    """

    event_id: str
    event_type: str  # "watchlist.item_added" or "watchlist.item_deleted"
    schema_version: int
    occurred_at: str
    user_id: str
    watchlist_id: str
    entity_ids_affected: tuple[str, ...] = ()  # always non-empty for valid events
    correlation_id: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "CanonicalWatchlistEvent":
        return cls(
            event_id=d["event_id"],
            event_type=d["event_type"],
            schema_version=d["schema_version"],
            occurred_at=d["occurred_at"],
            user_id=d["user_id"],
            watchlist_id=d["watchlist_id"],
            entity_ids_affected=tuple(d.get("entity_ids_affected", [])),
            correlation_id=d.get("correlation_id"),
        )

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at,
            "user_id": self.user_id,
            "watchlist_id": self.watchlist_id,
            "entity_ids_affected": list(self.entity_ids_affected),
            "correlation_id": self.correlation_id,
        }
```

#### Step 3 — Update `libs/contracts/src/contracts/versions.py`

Add 5 new version constants at the end of the file (do not modify existing constants):

```python
# Ingestion pipeline event schema versions
RAW_ARTICLE_SCHEMA_VERSION: int = 1
STORED_ARTICLE_SCHEMA_VERSION: int = 1
ENRICHED_ARTICLE_SCHEMA_VERSION: int = 1
SIGNAL_SCHEMA_VERSION: int = 1
WATCHLIST_EVENT_SCHEMA_VERSION: int = 1
```

#### Step 4 — Update `libs/contracts/src/contracts/__init__.py`

Add all 5 new classes and 5 new version constants to `__all__` and import them. Match the style of existing imports exactly:

```python
from contracts.canonical.ingestion import (
    CanonicalRawArticleEvent,
    CanonicalStoredArticleEvent,
    CanonicalEnrichedArticleEvent,
    CanonicalSignalEvent,
    CanonicalWatchlistEvent,
)
from contracts.versions import (
    # ... existing version imports ...
    RAW_ARTICLE_SCHEMA_VERSION,
    STORED_ARTICLE_SCHEMA_VERSION,
    ENRICHED_ARTICLE_SCHEMA_VERSION,
    SIGNAL_SCHEMA_VERSION,
    WATCHLIST_EVENT_SCHEMA_VERSION,
)
```

#### Step 5 — Create `libs/contracts/tests/test_ingestion_events.py`

Round-trip and field-parity tests:

```python
"""Tests for ingestion canonical event models.

Each model is tested for:
1. from_dict → to_dict round-trip (no data loss)
2. Frozen dataclass (FrozenInstanceError on mutation attempt)
3. Field-level assertions for defaults and type coercions
"""
import dataclasses
import pytest
from contracts import (
    CanonicalRawArticleEvent,
    CanonicalStoredArticleEvent,
    CanonicalEnrichedArticleEvent,
    CanonicalSignalEvent,
    CanonicalWatchlistEvent,
)

# ── CanonicalRawArticleEvent ──────────────────────────────────────────────────

RAW_ARTICLE_DICT = {
    "event_id": "evt-001",
    "event_type": "content.article.raw",
    "schema_version": 1,
    "occurred_at": "2026-01-15T12:00:00Z",
    "url_hash": "abc123",
    "source_id": "eodhd",
    "source_domain": "seekingalpha.com",
    "url": "https://seekingalpha.com/article/1234",
    "minio_bucket": "raw-articles",
    "minio_key": "s4/content/raw/2026/01/15/abc123.html",
    "title": "Apple Q4 Earnings Beat",
    "content_type": "text/html",
    "correlation_id": "corr-001",
}

def test_raw_article_round_trip():
    event = CanonicalRawArticleEvent.from_dict(RAW_ARTICLE_DICT)
    assert event.to_dict() == RAW_ARTICLE_DICT

def test_raw_article_defaults():
    d = {k: v for k, v in RAW_ARTICLE_DICT.items() if k not in ("title", "content_type", "correlation_id")}
    event = CanonicalRawArticleEvent.from_dict(d)
    assert event.title is None
    assert event.content_type == "text/html"
    assert event.correlation_id is None

def test_raw_article_frozen():
    event = CanonicalRawArticleEvent.from_dict(RAW_ARTICLE_DICT)
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.event_id = "modified"  # type: ignore[misc]


# ── CanonicalStoredArticleEvent ───────────────────────────────────────────────

STORED_ARTICLE_DICT = {
    "event_id": "evt-002",
    "event_type": "content.article.stored",
    "schema_version": 1,
    "occurred_at": "2026-01-15T12:01:00Z",
    "article_id": "doc-uuid-001",
    "source_domain": "seekingalpha.com",
    "title": "Apple Q4 Earnings Beat",
    "url": "https://seekingalpha.com/article/1234",
    "language": "en",
    "word_count": 842,
    "is_duplicate": False,
    "duplicate_of": None,
    "published_at": "2026-01-15T10:00:00Z",
    "correlation_id": "corr-001",
}

def test_stored_article_round_trip():
    event = CanonicalStoredArticleEvent.from_dict(STORED_ARTICLE_DICT)
    assert event.to_dict() == STORED_ARTICLE_DICT

def test_stored_article_is_duplicate_default():
    d = {k: v for k, v in STORED_ARTICLE_DICT.items() if k not in ("is_duplicate", "duplicate_of")}
    event = CanonicalStoredArticleEvent.from_dict(d)
    assert event.is_duplicate is False
    assert event.duplicate_of is None


# ── CanonicalEnrichedArticleEvent ─────────────────────────────────────────────

ENRICHED_ARTICLE_DICT = {
    "event_id": "evt-003",
    "event_type": "nlp.article.enriched",
    "schema_version": 1,
    "occurred_at": "2026-01-15T12:05:00Z",
    "article_id": "doc-uuid-001",
    "embedding_model": "bge-large-en-v1.5",
    "entity_count": 3,
    "event_count": 1,
    "sentiment_label": "positive",
    "sentiment_score": 0.82,
    "topic_cluster_id": "cluster-42",
    "correlation_id": "corr-001",
}

def test_enriched_article_round_trip():
    event = CanonicalEnrichedArticleEvent.from_dict(ENRICHED_ARTICLE_DICT)
    assert event.to_dict() == ENRICHED_ARTICLE_DICT

def test_enriched_article_embedding_model_default():
    """Schema default is all-MiniLM-L6-v2 for backward compat; active model is bge-large-en-v1.5."""
    d = {k: v for k, v in ENRICHED_ARTICLE_DICT.items() if k != "embedding_model"}
    event = CanonicalEnrichedArticleEvent.from_dict(d)
    assert event.embedding_model == "all-MiniLM-L6-v2"  # schema compat default


# ── CanonicalSignalEvent ──────────────────────────────────────────────────────

SIGNAL_DICT = {
    "event_id": "evt-004",
    "event_type": "nlp.signal.detected",
    "schema_version": 1,
    "occurred_at": "2026-01-15T12:06:00Z",
    "entity_id": "entity-uuid-aapl",
    "signal_type": "earnings_beat",
    "title": "Apple Q4 EPS beats consensus by 12%",
    "severity": 3,
    "source_article_ids": ["doc-uuid-001", "doc-uuid-002"],
    "details": '{"eps_beat_pct": 12.3, "consensus": 2.15}',
    "correlation_id": "corr-001",
}

def test_signal_round_trip():
    event = CanonicalSignalEvent.from_dict(SIGNAL_DICT)
    result = event.to_dict()
    assert result["source_article_ids"] == SIGNAL_DICT["source_article_ids"]  # list preserved
    assert event.source_article_ids == tuple(SIGNAL_DICT["source_article_ids"])  # tuple internally

def test_signal_source_article_ids_empty_default():
    d = {k: v for k, v in SIGNAL_DICT.items() if k != "source_article_ids"}
    event = CanonicalSignalEvent.from_dict(d)
    assert event.source_article_ids == ()
    assert event.to_dict()["source_article_ids"] == []


# ── CanonicalWatchlistEvent ───────────────────────────────────────────────────

WATCHLIST_ADDED_DICT = {
    "event_id": "evt-005",
    "event_type": "watchlist.item_added",
    "schema_version": 1,
    "occurred_at": "2026-01-15T12:10:00Z",
    "user_id": "user-uuid-001",
    "watchlist_id": "wl-uuid-001",
    "entity_ids_affected": ["entity-uuid-aapl"],
    "correlation_id": None,
}

WATCHLIST_DELETED_DICT = {**WATCHLIST_ADDED_DICT, "event_type": "watchlist.item_deleted"}

def test_watchlist_added_round_trip():
    event = CanonicalWatchlistEvent.from_dict(WATCHLIST_ADDED_DICT)
    assert event.to_dict() == WATCHLIST_ADDED_DICT

def test_watchlist_deleted_round_trip():
    event = CanonicalWatchlistEvent.from_dict(WATCHLIST_DELETED_DICT)
    assert event.event_type == "watchlist.item_deleted"

def test_watchlist_event_type_deleted_not_removed():
    """Regression: event_type must be 'watchlist.item_deleted', not 'watchlist.item_removed'."""
    event = CanonicalWatchlistEvent.from_dict(WATCHLIST_DELETED_DICT)
    assert event.event_type != "watchlist.item_removed"
    assert event.event_type == "watchlist.item_deleted"

def test_watchlist_entity_ids_tuple_internally():
    event = CanonicalWatchlistEvent.from_dict(WATCHLIST_ADDED_DICT)
    assert isinstance(event.entity_ids_affected, tuple)

def test_watchlist_entity_ids_list_in_to_dict():
    event = CanonicalWatchlistEvent.from_dict(WATCHLIST_ADDED_DICT)
    assert isinstance(event.to_dict()["entity_ids_affected"], list)
```

#### Step 6 — Update `docs/libs/contracts.md`

Add the following sections to the existing `docs/libs/contracts.md` documentation:

1. **New canonical models table entry** — add a row for each of the 5 new models in the "Canonical Models" table:

   | Model | Avro schema | Producer | Consumer | Version constant |
   |-------|-------------|----------|---------|-----------------|
   | `CanonicalRawArticleEvent` | `content.article.raw.v1.avsc` | S4 | S5 | `RAW_ARTICLE_SCHEMA_VERSION` |
   | `CanonicalStoredArticleEvent` | `content.article.stored.v1.avsc` | S5 | S6 | `STORED_ARTICLE_SCHEMA_VERSION` |
   | `CanonicalEnrichedArticleEvent` | `nlp.article.enriched.v1.avsc` | S6 | S7 | `ENRICHED_ARTICLE_SCHEMA_VERSION` |
   | `CanonicalSignalEvent` | `nlp.signal.detected.v1.avsc` | S6 | S10 | `SIGNAL_SCHEMA_VERSION` |
   | `CanonicalWatchlistEvent` | `portfolio.watchlist.updated.v1.avsc` | S1 | S10 | `WATCHLIST_EVENT_SCHEMA_VERSION` |

2. **Schema version constants section** — add the 5 new constants alongside existing ones.

3. **Ingestion event models section** — new subsection with:
   - Explanation of the `article_id` field on `CanonicalStoredArticleEvent` and `CanonicalEnrichedArticleEvent` (maps to `doc_id` in `content_store_db`; field name preserved for Avro schema backward compatibility)
   - Warning about `CanonicalEnrichedArticleEvent.embedding_model` default mismatch (schema default = `all-MiniLM-L6-v2`; active model = `bge-large-en-v1.5`)
   - Warning about `CanonicalWatchlistEvent`: `event_type` must be `"watchlist.item_deleted"`, never `"watchlist.item_removed"`
   - Note that `source_article_ids` and `entity_ids_affected` are stored as `tuple` internally (frozen dataclass) but serialized as `list` in `to_dict()` for Avro compatibility

4. **Updated "How to bump a schema version"** section — add note: bump the version constant in `versions.py`, add a new field with a default to the Avro schema, update `from_dict` to read the new field with `d.get("new_field", default)`, bump `schema_version` default in the dataclass.

5. **Updated common pitfalls** — add pitfall: "Using `list` for `source_article_ids` or `entity_ids_affected` in a frozen dataclass — these fields are `tuple` internally; `to_dict()` converts to `list` for Avro. Don't mutate after construction."

**Validation gate** (run before marking T-F-013 done):
```bash
# Lint + type-check
cd libs/contracts
ruff check src/ tests/
mypy src/

# Run unit tests
python -m pytest tests/test_ingestion_events.py -v
# All tests must pass

# Run full contracts test suite
python -m pytest tests/ -v
# Existing tests must still pass

# Run gen-contracts.sh
cd /path/to/repo/root
./scripts/gen-contracts.sh
# Must exit 0
```

---

## Constraints

- T-F-012: Do NOT change `replication-factor` on any existing topic.
- T-F-012: Do NOT remove any existing topic from the script.
- T-F-012: `entity.dirtied.v1` must use `--config cleanup.policy=compact` — it is NOT a time-retention topic.
- T-F-012: The `--if-not-exists` flag must be present on every `--create` call for idempotency.
- T-F-013: Do NOT rename `article_id` to `doc_id` in `CanonicalStoredArticleEvent` or `CanonicalEnrichedArticleEvent` — the Avro schema uses `article_id`; field name parity is the contract.
- T-F-013: Do NOT add `@abstractmethod` or inherit from ABC — frozen dataclasses with `from_dict`/`to_dict` only.
- T-F-013: `source_article_ids` on `CanonicalSignalEvent` and `entity_ids_affected` on `CanonicalWatchlistEvent` must be `tuple` internally (frozen constraint) and `list` in `to_dict()` (Avro array compatibility).
- T-F-013: `CanonicalWatchlistEvent` must include a docstring-level warning: event_type = "watchlist.item_deleted" (never "watchlist.item_removed").
- T-F-013: Do NOT modify existing canonical model classes or existing version constants.

## Scope & token budget

**write_paths**:
```
infra/kafka/init/create-topics.sh                             # T-F-012
libs/contracts/src/contracts/canonical/ingestion.py           # T-F-013 (create)
libs/contracts/src/contracts/__init__.py                      # T-F-013 (update exports)
libs/contracts/src/contracts/versions.py                      # T-F-013 (add 5 constants)
libs/contracts/tests/test_ingestion_events.py                 # T-F-013 (create)
docs/libs/contracts.md                                        # T-F-013 (update)
```

**Exploration bound**: Read at most 8 files total before making any edit. All field specifications are in the Avro `.avsc` files (already listed in mandatory pre-read) and the response document.

**Stop condition**: If `scripts/gen-contracts.sh` fails for reasons other than the new schemas being absent from the registry (e.g., a pre-existing script error), stop and report before continuing.

## Required tests

```bash
# T-F-012
bash -n infra/kafka/init/create-topics.sh
# Exit 0

# T-F-013
cd libs/contracts
ruff check src/ tests/
mypy src/
python -m pytest tests/ -v

# Final — full contract validation
./scripts/gen-contracts.sh
```

**Pass criteria**:
- `bash -n` exits 0 (script is valid bash)
- `entity.dirtied.v1` present in script with `cleanup.policy=compact` and 24 partitions
- All 5 existing partition-count fixes present
- All 5 new topics present in script
- `ruff check` and `mypy --strict` pass on all new Python files
- All new round-trip tests pass
- `test_watchlist_event_type_deleted_not_removed` passes (regression guard)
- Existing `libs/contracts` tests still pass (no regression)
- `./scripts/gen-contracts.sh` exits 0

## Incremental quality gates (mandatory)

Run these gates **immediately after each task** — do not batch.

**After T-F-012**:
```bash
bash -n infra/kafka/init/create-topics.sh
# Must exit 0 — if fails, fix before continuing

grep "cleanup.policy=compact" infra/kafka/init/create-topics.sh
# Must return result

grep -c "if-not-exists" infra/kafka/init/create-topics.sh
# Must be >= 10 (one per topic --create call)
```

**After T-F-013**:
```bash
cd libs/contracts
ruff check src/ tests/
# Must exit 0

mypy src/
# Must exit 0

python -m pytest tests/test_ingestion_events.py -v
# All tests must pass

python -m pytest tests/ -v
# All existing tests must still pass
```

**No Deferred Fixes**: Do not carry ruff/mypy/test failures from T-F-012 into T-F-013. Fix immediately before continuing.

## Documentation requirements

All documentation must meet the **Documentation quality standard** (8 criteria from `docs/ai-interactions/agent-prompts/0000-exec-wave-generation-template.md`).

**Files to update in this wave**:
- `docs/libs/contracts.md` — add 5 new models, 5 version constants, ingestion event models section, updated pitfalls
- `docs/MASTER_PLAN.md §6.2` — update Kafka topic table: add 5 new topics, correct partition counts for the 5 existing topics that were wrong, note `entity.dirtied.v1` compaction policy

**N/A criteria for this wave**:
- Diagrams: N/A for T-F-012 (no new control flow). T-F-013: if a sequence diagram for "how S4 produces a CanonicalRawArticleEvent" is useful context, add it; otherwise N/A.
- Abstract methods documented: N/A — no abstract classes.
- Common pitfalls: REQUIRED in `docs/libs/contracts.md` — update pitfalls section with tuple/list serialization pitfall.
- Realistic code examples: REQUIRED — `docs/libs/contracts.md` must include a working code example of `CanonicalRawArticleEvent.from_dict(avro_payload).to_dict()` for round-trip use in a consumer.
- Lib docs updated: REQUIRED — `libs/contracts` surface changed; `docs/libs/contracts.md` must be updated in this wave.
- Service docs: N/A — no service behavior changed.

## Required handoff evidence

The executing agent must provide:

1. **Changed files list** (exact paths)
2. **Validation ledger**:
   | Command | Scope | Exit code | Result |
   |---------|-------|-----------|--------|
   | `bash -n infra/kafka/init/create-topics.sh` | T-F-012 | 0 | ✓ |
   | `grep "cleanup.policy=compact" create-topics.sh` | T-F-012 | 0 (match found) | ✓ |
   | `grep -c "if-not-exists" create-topics.sh` | T-F-012 | 0 | ≥10 |
   | `ruff check libs/contracts/src/ tests/` | T-F-013 | 0 | ✓ |
   | `mypy libs/contracts/src/` | T-F-013 | 0 | ✓ |
   | `pytest tests/test_ingestion_events.py -v` | T-F-013 | 0 | all pass |
   | `pytest libs/contracts/tests/ -v` | T-F-013 | 0 | all pass |
   | `./scripts/gen-contracts.sh` | All | 0 | ✓ |

3. **Documentation quality checklist**:
   | Criterion | Status | Notes |
   |-----------|--------|-------|
   | Accuracy verified | ✓ | Field names match Avro schemas exactly; partition counts match PRD §7 |
   | Diagrams for non-trivial flows | N/A | No new control flow |
   | Realistic code examples | ✓ | from_dict/to_dict example in docs/libs/contracts.md |
   | Abstract methods documented | N/A | No abstract classes |
   | Common pitfalls section | ✓ | tuple/list pitfall added to contracts.md |
   | Lib docs updated | ✓ | docs/libs/contracts.md updated with 5 new models |
   | Service docs reflect final state | ✓ | MASTER_PLAN §6.2 updated |
   | No orphan documentation | ✓ | |

4. **Commit message proposal**:
   ```
   feat: fix Kafka topic config + add ingestion canonical event models to libs/contracts

   Correct 5 partition counts in create-topics.sh (content.article.raw.v1: 3→12,
   nlp.signal.detected.v1: 3→24, etc.), add 5 new topics including compacted
   entity.dirtied.v1 (24 partitions). Add CanonicalRawArticleEvent, CanonicalStoredArticleEvent,
   CanonicalEnrichedArticleEvent, CanonicalSignalEvent, CanonicalWatchlistEvent to
   libs/contracts with round-trip tests and docs/libs/contracts.md update.
   ```

---

## Final wave: required PR description

This is the final wave of Prompt 0011 — Ingestion Pipeline v1 Foundations (Prompt 0011). The executing agent must include a PR description for the full scope (all 5 waves, all 13 tasks). Submit this as a comment on the PR or in the commit message body.

```markdown
## PR: Ingestion Pipeline v1 Foundations (Prompt 0011)

### Summary

Implements all 13 blocking prerequisites for the Worldview Intelligence Pipeline ingestion
services (S4, S5, S6, S7, S10). No service application logic is included — this PR
establishes contracts, schemas, database DDL, shared libraries, and infrastructure
configuration that all subsequent service implementation PRs depend on.

### Scope

**13 atomic tasks across 5 execution waves:**

| Wave | Tasks | What |
|------|-------|------|
| 01 | T-F-001, T-F-002, T-F-003 | §1.4 repository fixes (watchlist rename, 6 Avro schemas, kg config) |
| 02 | T-F-004, T-F-005, T-F-006 | `libs/ml-clients` — new 6th shared library (3 Protocols, 4 concrete adapters) |
| 03 | T-F-007, T-F-008, T-F-009 | `content_ingestion_db`, `content_store_db`, `nlp_db` Alembic migrations |
| 04 | T-F-010, T-F-011 | `intelligence-migrations` init container (full `intelligence_db` DDL) + S10 stub |
| 05 | T-F-012, T-F-013 | Kafka topic config + `libs/contracts` ingestion event models |

### Blocking fixes resolved (§1.4)

- **T-F-001** — Renamed `watchlist.item_removed` → `watchlist.item_deleted` in Avro schema and all Portfolio service references. Prevents S10 from silently dropping watchlist delete events.
- **T-F-002** — Created 6 missing Avro schema files required by `schema-init` (boot step 4). Without these, the cluster cannot boot.
- **T-F-003** — Fixed `knowledge-graph` service `DATABASE_URL` default from `kg_db` (non-existent) to `intelligence_db`. Prevents S7 startup failure.

### New shared library: `libs/ml-clients`

Sixth shared library providing ML provider abstractions for S6 (NLP Pipeline) and S7 (Knowledge Graph):
- 3 `typing.Protocol` interfaces: `EmbeddingClient`, `NERClient`, `ExtractionClient`
- 4 concrete adapters: `OllamaEmbeddingAdapter` (bge-large-en-v1.5), `OllamaExtractionAdapter` (Qwen2.5-7B-Instruct), `GLiNERLocalAdapter` (urchade/gliner_large-v2.1), `AnthropicExtractionAdapter` (claude-sonnet-4-6)
- All adapters raise only `RetryableError` or `FatalError` (from `libs/messaging`); no naked exceptions
- `asyncio.Semaphore` injected at construction; GLiNER runs via `run_in_executor` (non-blocking)

### Database schemas created

Five databases now have Alembic migrations ready:

| Database | Owner | Key tables | Notable |
|----------|-------|-----------|---------|
| `content_ingestion_db` | S4 | `fetch_log`, `outbox_events`, `dead_letter_queue` | Outbox pattern for S4→S5 |
| `content_store_db` | S5 | `documents`, `minhash_signatures` (INTEGER[]), `minhash_entity_mentions` | INTEGER[] for MinHash (never BYTEA) |
| `nlp_db` | S6 | 9 tables including `chunk_embeddings` + `section_embeddings` with HNSW partial indexes | HNSW via `op.execute()`; pgvector |
| `intelligence_db` | `intelligence-migrations` | 20+ tables; HASH-partitioned `relations` (×8); RANGE-partitioned evidence/claims/events | 6-row decay seed; 20-row relation_type seed |
| `alert_db` | S10 | `alert_subscriptions`, `alerts` (UNIQUE dedup_key), `alert_deliveries`, `pending_alerts` | Dedup gate enforced at DB level |

### Kafka infrastructure

- 5 existing topics corrected to PRD §7 partition counts (`content.article.raw.v1`: 3→12, `nlp.signal.detected.v1`: 3→24, etc.)
- 5 new topics added: `graph.state.changed.v1`, `intelligence.contradiction.v1`, `relation.type.proposed.v1`, `alert.delivered.v1`
- `entity.dirtied.v1` added as compacted topic (24 partitions, `cleanup.policy=compact`, key = `entity_id`)
- `relation.type.proposed.v1` Schema Registry FULL compatibility set in `register-schemas.py`
- All 16 Avro schemas now present in `infra/kafka/schemas/`

### `libs/contracts` additions

5 new frozen dataclasses with `from_dict`/`to_dict` for Avro interop:
`CanonicalRawArticleEvent`, `CanonicalStoredArticleEvent`, `CanonicalEnrichedArticleEvent`,
`CanonicalSignalEvent`, `CanonicalWatchlistEvent` — each with round-trip tests and
`fastavro` contract validation.

### Boot order satisfaction (PRD §12.1)

| Boot step | Satisfied by |
|-----------|-------------|
| Step 3 — kafka-init (10 topics) | T-F-012 |
| Step 4 — schema-init (16 Avro schemas) | T-F-001, T-F-002 |
| Step 5 — intelligence-migrations | T-F-010 |
| Step 8 — services start (all DB schemas exist) | T-F-007 (S4), T-F-008 (S5), T-F-009 (S6), T-F-010 (S7 via intelligence-migrations), T-F-011 (S10) |

### Architecture decisions

1. **`intelligence-migrations` init container** — `intelligence_db` DDL is owned exclusively by this standalone container; S6 and S7 set `ALEMBIC_ENABLED=false`. No cross-service DDL ownership.
2. **`typing.Protocol` over ABC** — `libs/ml-clients` uses structural typing for adapter interfaces; enables duck-typing without inheritance and simplifies testing with minimal mock classes.
3. **HNSW indexes via `op.execute()`** — Alembic's `op.create_index()` does not support `USING hnsw`; all HNSW index DDL uses raw SQL execution.
4. **`partition_key` as STORED computed column** — `relations.partition_key` and `relation_evidence_raw.partition_key` are `GENERATED ALWAYS AS (abs(hashtext(subject_entity_id::text)) % 8) STORED`. Never include in INSERT statements.
5. **MinHash as `INTEGER[]`** — `minhash_signatures.signature` is `INTEGER[]`, never `BYTEA`. Correct type for 128-band MinHash vector; enables Postgres array operators.
6. **Watchlist event type** — `watchlist.item_deleted` (not `watchlist.item_removed`). Breaking change: old consumers using `watchlist.item_removed` will silently drop delete events. Portfolio service updated; no other service depended on the old name.

### Validation evidence

All incremental quality gates passed per wave:
- `grep -r "watchlist.item_removed" services/ infra/kafka/schemas/` → 0 results
- `grep -r "kg_db" services/knowledge-graph/` → 0 results
- All 16 Avro schemas parse without error via `fastavro.schema.parse_schema`
- `libs/ml-clients`: `ruff check` + `mypy --strict` + unit tests pass
- All 5 Alembic migration files pass Python syntax validation
- `libs/contracts` round-trip tests: all pass; `scripts/gen-contracts.sh` exits 0
- `create-topics.sh` valid bash (`bash -n`); 10 topics; `entity.dirtied.v1` compacted

### What this PR does NOT include

- Service application logic (no FastAPI routes, no Kafka consumers, no use cases)
- `intelligence_db` Alembic config in S6 or S7 (forbidden by design)
- Docker Compose `depends_on` wiring (DevOps task; boot order is documented)
- Prompt 0016 content (S4/S5 implementation — now unblocked by this PR)
- Prompt 0017 content (S6/S7/S10 implementation — now unblocked by this PR)

### Test plan

- [ ] `grep -r "watchlist.item_removed" services/ infra/kafka/schemas/` returns 0 results
- [ ] `grep -r "kg_db" services/knowledge-graph/` returns 0 results
- [ ] `python -c "import json,pathlib,fastavro.schema; [fastavro.schema.parse_schema(json.load(open(f))) for f in pathlib.Path('infra/kafka/schemas').glob('*.avsc')]"` exits 0 for all 16 schemas
- [ ] `cd libs/ml-clients && pytest tests/ --ignore=tests/integration/ -v` passes
- [ ] `mypy --strict libs/ml-clients/src/` exits 0
- [ ] `python -c "import ast; ast.parse(open('services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py').read())"` exits 0
- [ ] `bash -n infra/kafka/init/create-topics.sh` exits 0
- [ ] `grep "cleanup.policy=compact" infra/kafka/init/create-topics.sh` returns result
- [ ] `cd libs/contracts && pytest tests/ -v` — all tests pass including 5 new ingestion event tests
- [ ] `./scripts/gen-contracts.sh` exits 0
- [ ] `cd services/alert && ruff check src/ && mypy src/` exits 0
- [ ] `from alert.config import Settings; s = Settings(); assert 'alert_db' in s.database_url` passes
```

## Definition of done

- [ ] `create-topics.sh` corrects 5 existing partition counts to PRD §7 values
- [ ] All 5 new topics added to `create-topics.sh` (graph.state.changed.v1, intelligence.contradiction.v1, relation.type.proposed.v1, alert.delivered.v1, entity.dirtied.v1)
- [ ] `entity.dirtied.v1` has `cleanup.policy=compact` and 24 partitions
- [ ] Custom retention config added for 4 topics (14d for signal+graph; 30d for contradiction+relation)
- [ ] Script is idempotent (all `--create` calls use `--if-not-exists`)
- [ ] `bash -n create-topics.sh` exits 0
- [ ] `libs/contracts/src/contracts/canonical/ingestion.py` created with 5 new frozen dataclasses
- [ ] 5 new version constants added to `versions.py`
- [ ] All 5 new classes and 5 new constants exported from `libs/contracts/__init__`
- [ ] `tests/test_ingestion_events.py` created with round-trip tests for all 5 models
- [ ] `test_watchlist_event_type_deleted_not_removed` regression test passes
- [ ] `ruff check` passes on all new Python files
- [ ] `mypy --strict` passes on `libs/contracts/src/`
- [ ] All existing `libs/contracts` tests still pass (no regression)
- [ ] `./scripts/gen-contracts.sh` exits 0
- [ ] `docs/libs/contracts.md` updated with 5 new models, version constants, ingestion section, updated pitfalls
- [ ] `docs/MASTER_PLAN.md §6.2` updated with corrected partition counts and 5 new topics
- [ ] Incremental quality gates passed for each task (no deferred failures)
- [ ] Commit message proposal provided
- [ ] Full PR description provided (this is the final wave)
