"""Unit tests for EconomicEventsWorker (Worker 13D-6) — PRD-0018 §6 Worker 13D-6."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_COUNTRY_ENTITY_ID = UUID("01910000-0000-7000-8000-000000000001")

# Patch paths — source module paths so lazy `from ... import X` picks up the mock
_TEMPORAL_EVENT_REPO = (
    "knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository.TemporalEventRepository"
)
_EXPOSURE_REPO = "knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository.EntityEventExposureRepository"  # noqa: E501
_ENTITY_REPO = "knowledge_graph.infrastructure.intelligence_db.repositories.entity_repository.EntityRepository"

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_repos(country_entity_id: UUID | None = _COUNTRY_ENTITY_ID) -> tuple[Any, Any, Any]:
    """Build mock repository instances (not classes — injected via return_value)."""
    event_repo = AsyncMock()
    event_repo.upsert_by_natural_key = AsyncMock(return_value=UUID("01910000-0000-7000-8000-000000000002"))

    exposure_repo = AsyncMock()
    exposure_repo.upsert = AsyncMock(return_value=UUID("01910000-0000-7000-8000-000000000003"))

    entity_repo = AsyncMock()
    entity_repo.find_country_entity = AsyncMock(return_value=country_entity_id)

    return event_repo, exposure_repo, entity_repo


def _make_session_factory() -> Any:
    """Build a mock session factory."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    sf = MagicMock()
    sf.return_value = session
    return sf


def _run_worker(
    eodhd_events: list[dict[str, Any]],
    country_entity_id: UUID | None = _COUNTRY_ENTITY_ID,
    countries: list[str] | None = None,
    side_effect: list[list[dict[str, Any]]] | None = None,
) -> tuple[Any, Any, Any]:
    """Helper: build worker + repos, patch classes, run worker, return repos."""
    from knowledge_graph.infrastructure.workers.economic_events_worker import EconomicEventsWorker

    if countries is None:
        countries = ["US"]

    event_repo, exposure_repo, entity_repo = _make_repos(country_entity_id)
    sf = _make_session_factory()

    eodhd_client = AsyncMock()
    if side_effect is not None:
        eodhd_client.get_economic_events = AsyncMock(side_effect=side_effect)
    else:
        eodhd_client.get_economic_events = AsyncMock(return_value=eodhd_events)

    worker = EconomicEventsWorker(
        session_factory=sf,
        eodhd_client=eodhd_client,
        countries=countries,
    )

    with (
        patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
        patch(_EXPOSURE_REPO, return_value=exposure_repo),
        patch(_ENTITY_REPO, return_value=entity_repo),
    ):
        asyncio.run(worker.run())

    return event_repo, exposure_repo, entity_repo


# ── Test: Happy Path ──────────────────────────────────────────────────────────


class TestEconomicEventsWorkerHappyPath:
    def test_upserts_released_events_and_links_country_entity(self) -> None:
        """Released event (actual not None) → upsert_by_natural_key + exposure upsert."""
        ev = {
            "date": "2026-04-07T00:00:00",
            "type": "CPI m/m",
            "period": "Mar 2026",
            "actual": 0.3,
            "estimate": 0.2,
            "previous": 0.4,
            "change_percentage": 50.0,
            "country": "US",
        }
        event_repo, exposure_repo, entity_repo = _run_worker([ev])

        event_repo.upsert_by_natural_key.assert_awaited_once()
        call_kwargs = event_repo.upsert_by_natural_key.call_args.kwargs
        assert call_kwargs["event_type"] == "macro"
        assert call_kwargs["scope"] == "NATIONAL"
        assert call_kwargs["region"] == "US"
        assert call_kwargs["title"] == "CPI m/m (US) — Mar 2026"
        assert call_kwargs["confidence"] == 1.0
        assert call_kwargs["residual_impact_days"] == 30

        # Exposure linked to the country entity
        exposure_repo.upsert.assert_awaited_once()
        exp_kwargs = exposure_repo.upsert.call_args.kwargs
        assert exp_kwargs["entity_id"] == _COUNTRY_ENTITY_ID
        assert exp_kwargs["exposure_type"] == "directly_affected"
        assert exp_kwargs["confidence"] == 1.0

    def test_description_includes_surprise_magnitude(self) -> None:
        """Surprise = actual - estimate is included in the description."""
        ev = {
            "date": "2026-04-07",
            "type": "NFP",
            "period": "Mar 2026",
            "actual": 250000,
            "estimate": 200000,
            "previous": 190000,
            "change_percentage": 25.0,
            "country": "US",
        }
        event_repo, _, _ = _run_worker([ev])

        call_kwargs = event_repo.upsert_by_natural_key.call_args.kwargs
        desc = call_kwargs["description"]
        assert "50000.00" in desc  # surprise = 250000 - 200000
        assert "beat" in desc

    def test_missed_estimate_direction(self) -> None:
        """actual < estimate → 'missed' in description."""
        ev = {
            "date": "2026-04-07",
            "type": "CPI",
            "period": "Mar 2026",
            "actual": 0.1,
            "estimate": 0.3,
            "previous": 0.2,
            "change_percentage": -50.0,
            "country": "US",
        }
        event_repo, _, _ = _run_worker([ev])

        call_kwargs = event_repo.upsert_by_natural_key.call_args.kwargs
        assert "missed" in call_kwargs["description"]

    def test_active_until_is_24h_after_active_from(self) -> None:
        """Economic events are point-in-time; active_until = active_from + 24h."""
        from datetime import timedelta

        ev = {
            "date": "2026-04-07",
            "type": "FOMC",
            "period": "Apr 2026",
            "actual": 5.25,
            "estimate": 5.25,
            "previous": 5.50,
            "change_percentage": 0.0,
            "country": "US",
        }
        event_repo, _, _ = _run_worker([ev])

        call_kwargs = event_repo.upsert_by_natural_key.call_args.kwargs
        delta = call_kwargs["active_until"] - call_kwargs["active_from"]
        assert delta == timedelta(hours=24)


# ── Test: Skips Unreleased Events ─────────────────────────────────────────────


class TestEconomicEventsWorkerSkipsUnreleased:
    def test_skips_event_with_null_actual(self) -> None:
        """actual=None → event skipped; upsert_by_natural_key never called."""
        ev_unreleased = {
            "date": "2026-04-08",
            "type": "GDP q/q",
            "period": "Q1 2026",
            "actual": None,  # Not yet released
            "estimate": 0.5,
            "previous": 0.3,
            "change_percentage": None,
            "country": "US",
        }
        event_repo, exposure_repo, _ = _run_worker([ev_unreleased])

        event_repo.upsert_by_natural_key.assert_not_awaited()
        exposure_repo.upsert.assert_not_awaited()

    def test_mixed_released_and_unreleased_events(self) -> None:
        """Mix of released and unreleased → only released events are upserted."""
        events = [
            {  # Released
                "date": "2026-04-07",
                "type": "CPI m/m",
                "period": "Mar 2026",
                "actual": 0.3,
                "estimate": 0.2,
                "previous": 0.4,
                "change_percentage": 50.0,
                "country": "US",
            },
            {  # Unreleased — should be skipped
                "date": "2026-04-08",
                "type": "PPI m/m",
                "period": "Mar 2026",
                "actual": None,
                "estimate": 0.2,
                "previous": 0.1,
                "change_percentage": None,
                "country": "US",
            },
        ]
        event_repo, _, _ = _run_worker(events)

        assert event_repo.upsert_by_natural_key.await_count == 1  # Only one event upserted

    def test_empty_events_list_does_nothing(self) -> None:
        """Empty EODHD response → no DB calls."""
        event_repo, exposure_repo, _ = _run_worker([])

        event_repo.upsert_by_natural_key.assert_not_awaited()
        exposure_repo.upsert.assert_not_awaited()


# ── Test: Deduplication ───────────────────────────────────────────────────────


class TestEconomicEventsWorkerDeduplication:
    def test_same_event_twice_calls_upsert_twice_but_db_deduplicates(self) -> None:
        """Running the worker twice with the same event calls upsert twice.

        The ON CONFLICT DO UPDATE in the repository handles DB-level deduplication.
        The worker does not short-circuit at the application layer — that would
        require a read-before-write that defeats the purpose of the natural key.
        """
        ev = {
            "date": "2026-04-07",
            "type": "FOMC Rate Decision",
            "period": "Apr 2026",
            "actual": 5.25,
            "estimate": 5.25,
            "previous": 5.25,
            "change_percentage": 0.0,
            "country": "US",
        }
        from knowledge_graph.infrastructure.workers.economic_events_worker import EconomicEventsWorker

        event_repo, exposure_repo, entity_repo = _make_repos()
        sf = _make_session_factory()

        eodhd_client = AsyncMock()
        eodhd_client.get_economic_events = AsyncMock(return_value=[ev])

        worker = EconomicEventsWorker(
            session_factory=sf,
            eodhd_client=eodhd_client,
            countries=["US"],
        )
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(worker.run())
            asyncio.run(worker.run())

        # Worker called upsert twice — DB constraint handles the conflict
        assert event_repo.upsert_by_natural_key.await_count == 2

    def test_no_country_entity_still_upserts_event(self) -> None:
        """When country entity not found, event is still upserted; exposure skipped."""
        ev = {
            "date": "2026-04-07",
            "type": "CPI",
            "period": "Mar 2026",
            "actual": 2.1,
            "estimate": 2.0,
            "previous": 1.9,
            "change_percentage": 10.5,
            "country": "EU",
        }
        # No country entity found (returns None)
        event_repo, exposure_repo, _ = _run_worker([ev], country_entity_id=None, countries=["EU"])

        # Event upserted
        event_repo.upsert_by_natural_key.assert_awaited_once()
        # Exposure NOT created (no country entity)
        exposure_repo.upsert.assert_not_awaited()


# ── Test: Prometheus metrics ──────────────────────────────────────────────────


class TestEconomicEventsWorkerMetrics:
    def test_prometheus_counter_incremented_per_country(self) -> None:
        """s7_economic_events_ingested_total incremented with country label."""
        from knowledge_graph.infrastructure.metrics.prometheus import s7_economic_events_ingested_total

        ev_us = {
            "date": "2026-04-07",
            "type": "CPI m/m",
            "period": "Mar 2026",
            "actual": 0.3,
            "estimate": 0.2,
            "previous": 0.4,
            "change_percentage": 50.0,
            "country": "US",
        }
        ev_de = {
            "date": "2026-04-07",
            "type": "CPI m/m",
            "period": "Mar 2026",
            "actual": 0.2,
            "estimate": 0.3,
            "previous": 0.1,
            "change_percentage": 100.0,
            "country": "DE",
        }

        before_us = s7_economic_events_ingested_total.labels(country="US")._value.get()
        before_de = s7_economic_events_ingested_total.labels(country="DE")._value.get()

        # One event per country
        _run_worker([ev_us, ev_de], countries=["US", "DE"], side_effect=[[ev_us], [ev_de]])

        after_us = s7_economic_events_ingested_total.labels(country="US")._value.get()
        after_de = s7_economic_events_ingested_total.labels(country="DE")._value.get()

        assert after_us - before_us == 1.0
        assert after_de - before_de == 1.0
