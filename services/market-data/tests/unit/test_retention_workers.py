"""Unit tests for market-data's retention-pruner wiring.

Verifies ``_build_retention_workers`` constructs the correct
``RetentionCleanupWorker`` set from settings, including market-data's OWN
``outbox_events`` pruner (same delivered-pileup failure mode as
content-ingestion — closed pre-emptively before it grows). The generic
batched-delete behaviour is covered by libs/messaging's
``test_table_retention.py``; these tests pin the service-specific policy.
"""

from __future__ import annotations

import pytest
from market_data.config import Settings
from market_data.infrastructure.messaging.outbox.dispatcher_main import _build_retention_workers

pytestmark = pytest.mark.unit


def test_builds_outbox_and_ingestion_events_workers() -> None:
    """Defaults enable both the outbox and ingestion_events pruners."""
    settings = Settings()  # type: ignore[call-arg]  # required fields set in conftest
    workers = _build_retention_workers(settings)

    by_table = {w.policy.table: w for w in workers}
    assert set(by_table) == {"outbox_events", "ingestion_events"}

    # ── outbox: delivered-only, on dispatched_at, short window ──────────────
    outbox = by_table["outbox_events"]
    assert outbox.policy.status_column == "status"
    assert outbox.policy.status_value == "delivered"  # NEVER pending/processing/failed/dead_letter
    assert outbox.policy.age_column == "dispatched_at"
    assert outbox.policy.pk_column == "id"
    assert outbox.policy.retention.total_seconds() == settings.outbox_retention_seconds
    assert outbox.interval_seconds == settings.outbox_prune_interval_seconds

    # ── ingestion_events: status-less, on occurred_at, long window ──────────
    ingest = by_table["ingestion_events"]
    assert ingest.policy.status_column is None
    assert ingest.policy.age_column == "occurred_at"
    assert ingest.policy.retention.days == settings.ingestion_events_retention_days
    assert ingest.interval_seconds == settings.ingestion_events_prune_interval_seconds


def test_zero_retention_disables_each_pruner(monkeypatch: pytest.MonkeyPatch) -> None:
    """A retention window of 0 removes that table's worker (env-toggleable)."""
    monkeypatch.setenv("MARKET_DATA_OUTBOX_RETENTION_SECONDS", "0")
    monkeypatch.setenv("MARKET_DATA_INGESTION_EVENTS_RETENTION_DAYS", "0")
    settings = Settings()  # type: ignore[call-arg]
    assert _build_retention_workers(settings) == []
