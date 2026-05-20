"""Unit tests for the default ``_dead_letter_impl`` on :class:`BaseKafkaConsumer`.

Covers LIB-002 / TASK-W2-06.  Three scenarios:

1. With a ``dlq_emitter`` configured: ``dead_letter()`` publishes a JSON
   failure envelope to ``<topic>.dead-letter.v1`` with the canonical
   ``X-Dead-Letter-*`` headers.
2. Without a ``dlq_emitter``: the default impl logs a warning
   (``dead_letter_no_emitter_configured``) and short-circuits — preserving
   historical behaviour for subclasses that only persist to a DB table.
3. Subclass override-compat: a subclass that overrides ``_dead_letter_impl``
   to write to a fake DB AND calls ``super()`` gets BOTH the DB write and
   the DLQ topic emission.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from messaging.kafka.consumer.base import (
    DLQ_TOPIC_SUFFIX,
    BaseKafkaConsumer,
    ConsumerConfig,
    DLQEmitterProtocol,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.consumer.errors import RetryableError

pytestmark = pytest.mark.unit


# ── Test doubles ──────────────────────────────────────────────────────────────


class _InMemoryUoW(UnitOfWorkProtocol):
    """No-op unit of work — keeps the tests free of any DB/Kafka coupling."""

    async def __aenter__(self) -> _InMemoryUoW:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class _RecordingDLQEmitter:
    """Captures every ``emit()`` call for assertion in tests.

    Intentionally a plain class (not ``MagicMock``) so the recorded args are
    typed dicts/strings, easier to assert against, and so we exercise the
    structural :class:`DLQEmitterProtocol` instead of a mock that satisfies
    any signature.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def emit(
        self,
        topic: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
        key: str | None = None,
    ) -> None:
        self.calls.append(
            {
                "topic": topic,
                "payload": payload,
                "headers": headers,
                "key": key,
            },
        )


class _BareConsumer(BaseKafkaConsumer[str]):
    """Minimal concrete consumer — relies on the default ``_dead_letter_impl``."""

    def __init__(
        self,
        dlq_emitter: DLQEmitterProtocol | None = None,
        config: ConsumerConfig | None = None,
    ) -> None:
        super().__init__(
            config=config or ConsumerConfig(),
            dlq_emitter=dlq_emitter,
        )

    # ── Abstract interface ────────────────────────────────────────────────────

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        pass

    async def is_duplicate(self, event_id: str) -> bool:
        return False

    async def mark_processed(self, event_id: str) -> None:
        pass

    async def store_failure(self, failure: FailureInfo[str]) -> str:
        return failure.event_id

    async def update_failure(self, failure: FailureInfo[str]) -> None:
        pass

    async def get_pending_retries(self) -> list[FailureInfo[str]]:
        return []

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _InMemoryUoW()

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        return json.loads(raw)

    def get_schema_path(self, topic: str) -> str | None:
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", "unknown"))

    async def process_message_from_failure(self, failure: FailureInfo[str]) -> None:
        pass


class _OverridingConsumer(_BareConsumer):
    """Subclass that performs a DB-style write AND calls super() for topic emit.

    Exercises the back-compat contract documented on ``_dead_letter_impl``:
    a subclass override that calls ``await super()._dead_letter_impl(failure)``
    after its own side effect should observe both effects.
    """

    def __init__(
        self,
        dlq_emitter: DLQEmitterProtocol | None = None,
        config: ConsumerConfig | None = None,
    ) -> None:
        super().__init__(dlq_emitter=dlq_emitter, config=config)
        # Stand-in for a DLQ DB table — captures the failures the subclass
        # persisted on top of the inherited topic emission.
        self.db_writes: list[FailureInfo[str]] = []

    async def _dead_letter_impl(self, failure: FailureInfo[str]) -> None:
        # Custom side effect first (simulates "INSERT INTO dead_letter_queue").
        self.db_writes.append(failure)
        # Then chain to the default impl so the DLQ topic still receives
        # the envelope — this is the documented opt-in pattern.
        await super()._dead_letter_impl(failure)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_failure(
    event_id: str = "evt-001",
    topic: str = "content.article.raw.v1",
) -> FailureInfo[str]:
    """Return a populated :class:`FailureInfo` for the tests."""
    return FailureInfo(
        event_id=event_id,
        topic=topic,
        partition=3,
        offset=42,
        attempt=5,
        last_error=RetryableError("simulated downstream failure"),
    )


# ── Test cases ────────────────────────────────────────────────────────────────


class TestDefaultDeadLetterImpl:
    async def test_emits_to_dlq_topic_with_envelope_and_headers(self) -> None:
        """Default impl publishes a JSON envelope and standard headers to ``<topic>.dead-letter.v1``."""
        emitter = _RecordingDLQEmitter()
        consumer = _BareConsumer(dlq_emitter=emitter)

        failure = _make_failure()
        await consumer.dead_letter(failure)

        # Exactly one emit() call.
        assert len(emitter.calls) == 1
        call = emitter.calls[0]

        # Topic = original topic with the canonical suffix.
        assert call["topic"] == f"{failure.topic}{DLQ_TOPIC_SUFFIX}"
        assert call["topic"] == "content.article.raw.v1.dead-letter.v1"

        # Key = event_id (so DLQ partitioning matches the original event).
        assert call["key"] == failure.event_id

        # Payload envelope carries the full failure context.
        payload = call["payload"]
        assert payload["event_id"] == failure.event_id
        assert payload["original_topic"] == failure.topic
        assert payload["partition"] == failure.partition
        assert payload["offset"] == failure.offset
        assert payload["attempt"] == failure.attempt
        assert "simulated downstream failure" in payload["error"]
        assert payload["error_type"] == "RetryableError"
        assert "dead_lettered_at" in payload
        assert payload["consumer_group"] == consumer._config.group_id

        # Canonical X-Dead-Letter-* headers.
        headers = call["headers"]
        assert headers is not None
        assert headers["X-Dead-Letter-Original-Topic"] == failure.topic
        assert headers["X-Dead-Letter-Event-Id"] == failure.event_id
        assert "simulated downstream failure" in headers["X-Dead-Letter-Error"]
        assert headers["X-Dead-Letter-Timestamp"] == payload["dead_lettered_at"]

    async def test_no_emitter_logs_warning_and_short_circuits(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Without a ``dlq_emitter``, the default impl logs a warning and returns.

        This preserves historical behaviour for subclasses whose DLQ contract
        is DB-only — they simply don't pass an emitter and the base no-ops.

        structlog writes to stdout (not stdlib ``logging``) so we assert via
        ``capsys`` rather than ``caplog`` — ops dashboards alert on the event
        name string ``dead_letter_no_emitter_configured``.
        """
        consumer = _BareConsumer(dlq_emitter=None)

        # Must not raise.
        await consumer.dead_letter(_make_failure())

        captured = capsys.readouterr()
        assert "dead_letter_no_emitter_configured" in captured.out, (
            "Expected dead_letter_no_emitter_configured warning, got stdout: " + captured.out
        )

    async def test_subclass_override_can_chain_super(self) -> None:
        """A subclass override + ``super()`` call gets BOTH DB write AND topic emit."""
        emitter = _RecordingDLQEmitter()
        consumer = _OverridingConsumer(dlq_emitter=emitter)

        failure = _make_failure(event_id="evt-chain", topic="nlp.article.enriched.v1")
        await consumer.dead_letter(failure)

        # 1. Subclass DB write captured the failure.
        assert len(consumer.db_writes) == 1
        assert consumer.db_writes[0].event_id == "evt-chain"

        # 2. Default impl (via super()) emitted to the DLQ topic.
        assert len(emitter.calls) == 1
        assert emitter.calls[0]["topic"] == "nlp.article.enriched.v1.dead-letter.v1"
        assert emitter.calls[0]["payload"]["event_id"] == "evt-chain"

    async def test_emit_failure_is_swallowed_and_logged(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """If the emitter raises, the consumer must NOT crash — log + continue.

        Operationally: by the time we reach ``_dead_letter_impl`` the message
        has already been retried + counted against the cap.  An emitter
        failure (broker down, etc.) must not prevent the consumer from
        continuing to process other messages.
        """

        class _FailingEmitter:
            async def emit(
                self,
                topic: str,
                payload: dict[str, Any],
                headers: dict[str, str] | None = None,
                key: str | None = None,
            ) -> None:
                raise RuntimeError("broker unreachable")

        consumer = _BareConsumer(dlq_emitter=_FailingEmitter())

        # Must not raise — the emit failure is swallowed.
        await consumer.dead_letter(_make_failure())

        captured = capsys.readouterr()
        assert "dead_letter_emit_failed" in captured.out, (
            "Expected dead_letter_emit_failed error log, got stdout: " + captured.out
        )
