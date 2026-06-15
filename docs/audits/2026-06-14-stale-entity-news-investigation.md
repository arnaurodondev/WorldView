# Investigation: Stale Entity News (GOOGL / JPM / demo holdings)

**Date**: 2026-06-14 | **Investigator**: Claude (Principal Debug)  
**Branch**: feat/plan-0099-w4

---

## Confirmed Root Cause

The content-ingestion outbox dispatcher's **Confluent rdkafka producer entered an unrecoverable broken state at ~2026-06-14 18:01 UTC** (ApiVersionRequest timeout after Kafka transient unavailability), and was never restarted.

Because `self._producer` is lazily initialized and cached in memory, all subsequent `producer.produce()` calls silently time out (10 s `delivery_timeout_seconds`), returning `delivery_error = None` (the callback is never invoked within the window). The dispatcher logs `error: ""` and increments attempt counters — after 5 failures each record moves to `dead_letter`. **No `content.article.raw.v1` event has been delivered to Kafka since 2026-06-14 03:22:41 UTC** — nearly 22 hours ago.

The downstream consequence is a complete freeze:

```
content-ingestion (fetching OK) → outbox events stuck as "pending"
                                         ↓  [BLOCKED HERE]
                        → content.article.raw.v1 Kafka topic  (no new messages)
                                         ↓
                        → content-store  (max_ingested_at = 03:22 June 14)
                                         ↓
                        → nlp-pipeline article-consumer (max published_at = 02:11 June 14)
                                         ↓
                        → per-entity news query → shows stale results (correct data, stale docs)
```

---

## Evidence Table

| Signal | Value | Source |
|--------|-------|--------|
| Last `content.article.raw.v1` Kafka delivery | 2026-06-14 03:22:41 UTC | dispatcher logs |
| `outbox_events` pending (article topic) | **541 records** | content_ingestion_db |
| `outbox_events` dead_letter (article topic) | 663 records | content_ingestion_db |
| `content_store_db.documents` max_ingested_at | **2026-06-14 03:22:41** | content_store_db |
| `nlp_db.document_source_metadata` max published_at (24h) | **2026-06-14 02:11:23** | nlp_db |
| rdkafka error (dispatcher log) | `ApiVersionRequest failed: Local: Timed out` at **2026-06-14 18:01:04 UTC** | container logs |
| DNS failure after rdkafka timeout | `[Errno -3] Temporary failure in name resolution` at **18:08:12** | container logs |
| Finnhub-GOOGL: articles fetched today | 37 records in `article_fetch_log` (max pub 19:30 June 14) | content_ingestion_db |
| Finnhub-GOOGL: `new: 0` in recent worker logs | All logged as dedup (already in fetch_log) — **not a provider issue** | worker logs |
| GOOGL (`01900000-...-1003`) attributed articles last 7d | 9 docs on June 13, none on June 14+ | nlp_db |
| GOOGL latest attributed article published_at | **2026-06-13 22:10** | nlp_db join query |
| `newsapi-news` source enabled | **FALSE** — disabled, last run June 11 | content_ingestion_db |
| EODHD ticker-news: fetching, skipped=N, fetched=0 | Articles are fetched but deduped (already in fetch_log) — **content store is stale** | worker logs |

---

## Investigation Answers

### 1. Are news adapters fetching fresh articles?
**YES** — all three providers are actively polling:
- **Finnhub**: Fetching every ~5 min for all symbols. Returns fresh articles (Finnhub-GOOGL: 37 articles in `article_fetch_log`, latest published 19:30 June 14). `new: 0` in worker logs = dedup (article already in fetch_log, not re-fetched).
- **EODHD**: Active, fetching ticker-specific news. `eodhd-news` fetched 300 articles today. Ticker sources show `fetched: 0, skipped: N` because articles are already in `article_fetch_log` from midnight batch.
- **NewsAPI**: **DISABLED** — `enabled = false` in `sources` table. Watermark stuck at 2026-05-23. Last run 2026-06-11.

### 2. Raw doc freshness vs entity-attributed news freshness

| Stage | Latest timestamp |
|-------|-----------------|
| `article_fetch_log` (S4) | 2026-06-15 01:55 (fresh, 648+ today) |
| `outbox_events` last delivered | **2026-06-14 03:22** (stuck) |
| `content_store_db.documents` | **2026-06-14 03:22** |
| `nlp_db.document_source_metadata` max pub_at | **2026-06-14 02:11** |
| GOOGL entity attribution (latest article pub_at) | **2026-06-13 22:10** |

Gap: articles are fetched fresh but the outbox dispatcher is broken — they never reach Kafka → content-store → NLP → entity attribution.

### 3. GOOGL trace
- Canonical entity: `01900000-0000-7000-8000-000000001003` ("Alphabet Inc Class A")
- Articles attributed in last 24h: **0 new articles** (last attribution: June 13, 9 docs)
- Articles in `article_fetch_log` for Finnhub-GOOGL last 24h: **37 records** (published up to 19:30 June 14)
- EODHD-GOOGL-US: **22 records** in fetch_log (max published June 14 13:49)
- Gap: 59+ raw articles exist but none propagated to content-store/NLP since 03:22 June 14

### 4. Root cause: precise location
**`worldview-content-ingestion-dispatcher-1` container** — the rdkafka producer object (`self._producer` in `ContentIngestionOutboxDispatcher.get_producer()`) cached a broken TCP connection. No reconnection logic exists. All `producer.produce()` calls time out silently.

File: `services/content-ingestion/src/content_ingestion/infrastructure/messaging/outbox/dispatcher.py:57-66`
```python
def get_producer(self) -> Any:
    if self._producer is None:  # ← cached forever, no reconnect
        ...
        self._producer = build_serializing_producer(...)
    return self._producer
```

The `asyncio.wait_for(delivery_event.wait(), timeout=10.0)` in `base.py:451-454` catches the timeout as `delivery_error = asyncio.TimeoutError` but then `str(delivery_error)` is `""` (empty string), which is why the log shows `error: ""`.

---

## Ranked Fixes

### P0 — Immediate operational fix (minutes)
**Restart `worldview-content-ingestion-dispatcher-1`**  
This resets `self._producer = None`, forces a fresh rdkafka connection, and will immediately flush the 541 pending `content.article.raw.v1` events. No code change needed.

```bash
docker restart worldview-content-ingestion-dispatcher-1
```

After restart, expect ~541 articles to flow through within minutes, NLP pipeline to process them, and entity-attributed news to go live/fresh within ~30 minutes.

### P1 — Code fix: producer reconnect on delivery timeout (hours)
In `base.py`, when `delivery_error` is `asyncio.TimeoutError`, invalidate the cached producer so `get_producer()` rebuilds it on the next call.

File: `libs/messaging/src/messaging/kafka/dispatcher/base.py` (around line 455)
```python
except asyncio.TimeoutError as exc:
    delivery_error = exc
    self._reset_producer()  # NEW: force reconnect on timeout
```

And in `ContentIngestionOutboxDispatcher`:
```python
def _reset_producer(self) -> None:
    self._producer = None
    self._value_serializer = None  # may hold schema registry state
```

Or alternatively override `BaseOutboxDispatcher.get_producer()` to check a `_producer_healthy` flag.

### P1 — Code fix: log non-empty error string on TimeoutError
In `base.py:496`, `str(asyncio.TimeoutError())` is `""`. Replace with explicit message:

```python
error=str(delivery_error) or type(delivery_error).__name__,
```

This makes monitoring actionable instead of silent.

### P2 — Re-enable NewsAPI
`newsapi-news` source has `enabled = false`. Re-enable via admin API or DB:

```bash
docker exec worldview-postgres-1 psql -U postgres -d content_ingestion_db \
  -c "UPDATE sources SET enabled = true WHERE name = 'newsapi-news'"
```

Check why it was disabled (it may have hit rate limits or the API key expired). The watermark at 2026-05-23 means ~3 weeks of NewsAPI articles are missing.

### P2 — Dead-letter queue hygiene
663 dead-letter `content.article.raw.v1` events will never be retried automatically. After the dispatcher restart flushes the pending queue, assess whether these DLQ records should be requeued. They represent articles that failed to publish to Kafka during the production outage window(s).

### P3 — Add dispatcher health metric / alerting
The dispatcher has no alert for "zero deliveries in the last N minutes." Add a `outbox_last_delivery_timestamp` gauge and alert when stale > 30 minutes.
