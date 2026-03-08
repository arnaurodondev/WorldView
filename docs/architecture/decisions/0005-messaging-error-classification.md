# ADR-0005: Messaging Error Classification — Retryable vs Fatal

**Date**: 2026-03-08
**Status**: Accepted
**Deciders**: Architecture Decision Lead, Data Platform Engineer

---

### Context

Every Kafka consumer in the Worldview platform must make a decision when
message processing fails: **retry the message** or **discard it to a
dead-letter queue (DLQ)**.  Without an explicit classification, each
service team makes ad-hoc decisions, leading to:

- Inconsistent retry behavior (some consumers swallowing permanent errors
  and looping forever, others discarding transient errors and losing data).
- Unclear alerting thresholds (when should ops be paged?).
- No shared vocabulary for describing failure modes across code reviews and
  post-mortems.

### Decision

Adopt a **two-branch error hierarchy** in `libs/messaging`:

```
ConsumerError
├── RetryableError          ← transient; back off and retry
│   ├── StorageUnavailableError
│   ├── DatabaseConnectionError
│   ├── NetworkTimeoutError
│   ├── ServiceUnavailableError
│   └── RateLimitedError
└── FatalError              ← permanent; dead-letter immediately
    ├── SchemaVersionError
    ├── MalformedDataError
    ├── MissingRequiredFieldError
    └── BusinessRuleViolationError
```

#### Retry strategy

| Error branch | Action | Back-off |
|--------------|--------|----------|
| `RetryableError` | Retry up to `ConsumerConfig.max_retries` (default 5) | Full-jitter exponential: `random(0, min(60s, base * multiplier^attempt))` |
| `FatalError` | Dead-letter immediately | N/A |
| Unclassified `Exception` | Treat as `RetryableError` (safe default) | Same as retryable |

Initial back-off: 1 s.  Max back-off: 60 s.  Multiplier: 2.0.

#### Dead-letter queue semantics

When a message is dead-lettered:
1. The record is written to the service's `dead_letter` DB table (or
   a DLQ Kafka topic, service-dependent).
2. A `CRITICAL` structured log event is emitted.
3. An alert fires (see alerting implications below).

#### Alerting implications

| Condition | Severity | Action |
|-----------|----------|--------|
| Any `FatalError` | `ERROR` log + page | Immediate investigation required |
| Retryable error, attempt ≥ 3 | `WARNING` log | Track in monitoring dashboard |
| Record dead-lettered (attempts exhausted) | `CRITICAL` log + page | Data loss risk — escalate |

#### Consumer idempotency requirement

Every consumer **must** implement `is_duplicate(event_id)`.  The `event_id`
field in the Kafka envelope (a UUIDv7) is the idempotency key.  The dedup
table schema:

```sql
CREATE TABLE processed_events (
    event_id    UUID PRIMARY KEY,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Services are free to add a TTL-based cleanup job (e.g. delete rows older
than 7 days) as long as the Kafka topic retention is shorter.

#### Outbox dispatcher error handling

The :class:`~messaging.kafka.dispatcher.base.BaseOutboxDispatcher` uses the
same `max_attempts` cap.  Delivery failures (Kafka broker errors, timeouts)
are treated as retryable until `DispatcherConfig.max_attempts` (default 5)
is reached, at which point the outbox record moves to dead-letter.

### Consequences

#### Positive
- Consistent retry behavior across all 9 services.
- `FatalError` messages are never retried, preventing infinite loops on
  bad data.
- Shared vocabulary simplifies code review and post-mortems.
- Subclasses can refine classification by re-raising a more specific
  exception subclass.

#### Negative
- Developers must correctly classify new error types; misclassifying a
  fatal error as retryable causes redundant retries (and vice versa).
- The hierarchy is defined in `libs/messaging`; changes affect all services.

#### Neutral
- Unclassified exceptions are treated as retryable (conservative default).
  This can mask permanent bugs if developers rely on auto-retry rather than
  fixing root causes.

### Alternatives Considered

| Alternative | Pros | Cons | Why Rejected |
|-------------|------|------|--------------|
| Per-service error taxonomies | Full autonomy | Inconsistent behavior; duplicated logic | Rejected |
| Three-branch (transient / permanent / unknown) | Explicit unknown handling | Adds complexity with little benefit | Rejected — unknown defaults to retryable |
| Exception attributes (e.g. `is_retryable: bool`) | Flexible | Attributes can be omitted; hierarchy is self-documenting | Rejected — inheritance is the safer contract |

### References

- `libs/messaging/src/messaging/kafka/consumer/errors.py` — error hierarchy
- `libs/messaging/src/messaging/kafka/consumer/base.py` — retry logic
- `docs/libs/messaging.md` — consumer common pitfalls
- RULES.md R3 — idempotent consumers
