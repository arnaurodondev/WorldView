"""Tests for scripts/ops/recover_unprocessed_articles.py (P0-③, 2026-06-18).

The recovery script re-publishes ``content.article.stored.v1`` for every
``content_store`` document that lacks a ``routing_decision`` — the durable
signature of an article that was dead-lettered by the watchdog timeout before
it produced any routing decision (whole-article rollback).

These are hermetic, DB-free tests covering:
- the unprocessed-cohort selector (pure set difference),
- the stored-payload builder (schema fields + fresh event_id for idempotency),
- the documented dry-run / limit behaviour (no DB writes on dry-run).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

# Load the script as a module without making scripts/ops a package.  We register
# it in sys.modules BEFORE exec so its module-level @dataclass can resolve its
# own __module__ during type introspection (Python 3.12 _is_type lookup).
_SCRIPT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "ops", "recover_unprocessed_articles.py"),
)
_spec = importlib.util.spec_from_file_location("recover_unprocessed_articles", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
recover = importlib.util.module_from_spec(_spec)
sys.modules["recover_unprocessed_articles"] = recover
_spec.loader.exec_module(recover)


def _doc(doc_id: UUID, **overrides: object) -> object:
    base = {
        "doc_id": doc_id,
        "source_type": "eodhd",
        "title": "Example headline",
        "content_hash": "ch",
        "normalized_hash": "nh",
        "dedup_result": "unique",
        "minio_silver_key": "silver/x.json",
        "word_count": 500,
        "published_at": datetime(2026, 6, 12, tzinfo=UTC),
        "is_backfill": False,
        "tenant_id": None,
    }
    base.update(overrides)
    return recover.DocRow(**base)  # type: ignore[arg-type]


def test_script_file_exists() -> None:
    assert os.path.isfile(_SCRIPT_PATH)


class TestSelectUnprocessed:
    def test_returns_docs_without_routing_decision(self) -> None:
        a, b, c = uuid4(), uuid4(), uuid4()
        all_docs = {a, b, c}
        processed = {b}  # b already has a routing_decision
        result = recover.select_unprocessed_doc_ids(all_docs, processed)
        assert result == {a, c}

    def test_empty_when_all_processed(self) -> None:
        a, b = uuid4(), uuid4()
        assert recover.select_unprocessed_doc_ids({a, b}, {a, b}) == set()

    def test_ignores_processed_ids_not_in_content_store(self) -> None:
        # A routing_decision for a doc no longer in content_store must not break
        # the difference (it simply isn't in the unprocessed set).
        a = uuid4()
        ghost = uuid4()
        assert recover.select_unprocessed_doc_ids({a}, {a, ghost}) == set()


class TestBuildStoredPayload:
    def test_payload_has_requeue_fields(self) -> None:
        doc_id = uuid4()
        payload = recover.build_stored_payload(_doc(doc_id))
        assert payload["doc_id"] == str(doc_id)
        assert payload["minio_silver_key"] == "silver/x.json"
        assert payload["event_type"] == "content.article.stored"
        assert payload["schema_version"] == 1
        # published_at serialised to ISO string.
        assert payload["published_at"].startswith("2026-06-12")

    def test_fresh_event_id_each_call_for_idempotency(self) -> None:
        """A new event_id per build means consumer dedup never short-circuits a replay."""
        doc = _doc(uuid4())
        ids = {recover.build_stored_payload(doc)["event_id"] for _ in range(5)}
        assert len(ids) == 5  # all distinct

    def test_null_published_at_serialises_to_none(self) -> None:
        payload = recover.build_stored_payload(_doc(uuid4(), published_at=None))
        assert payload["published_at"] is None


class TestEnqueueDryRun:
    async def test_dry_run_writes_nothing_and_counts_docs(self) -> None:
        """Dry-run returns the doc count without touching the DB connections."""
        docs = [_doc(uuid4()), _doc(uuid4())]

        class _ExplodingConn:
            async def execute(self, *a: object, **k: object) -> None:
                raise AssertionError("dry-run must not write")

            def transaction(self) -> object:
                raise AssertionError("dry-run must not open a transaction")

        n = await recover._enqueue_recovery(_ExplodingConn(), _ExplodingConn(), docs, dry_run=True)
        assert n == 2

    async def test_empty_batch_is_noop(self) -> None:
        n = await recover._enqueue_recovery(None, None, [], dry_run=False)  # type: ignore[arg-type]
        assert n == 0
