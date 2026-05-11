"""Unit tests for FundamentalsDescriptionConsumer (T-D-3-10) — Consumer 13D-5.

Covers:
- Existing: description change detection (delegates to DefinitionRefreshWorker)
- New (B-1): metadata enrichment (employee_count, revenue_ttm_usd, pct_insiders,
  pct_institutions) via EntityRepository.update_metadata
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

_INSTRUMENT_ID = str(uuid4())

_FULL_PAYLOAD = {
    "General": {
        "Description": "Apple Inc. designs and sells consumer electronics.",
        "FullTimeEmployees": 164000,
    },
    "Highlights": {
        "RevenueTTM": 394328000000,
    },
    "SharesStats": {
        "PercentInsiders": 0.07,
        "PercentInstitutions": 60.52,
    },
}

_DESCRIPTION_ONLY_PAYLOAD = {
    "General": {
        "Description": "Apple Inc. designs and sells consumer electronics.",
    },
}


def _make_consumer():
    """Build a FundamentalsDescriptionConsumer with mocked dependencies."""
    from knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer import FundamentalsDescriptionConsumer

    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="kg-fundamentals-test",
        topics=["market.dataset.fetched"],
    )

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    sf = MagicMock()
    sf.return_value = session

    def_worker = AsyncMock()
    def_worker.refresh_for_entity = AsyncMock()

    storage = AsyncMock()

    consumer = FundamentalsDescriptionConsumer(
        config=config,
        session_factory=sf,
        definition_worker=def_worker,
        storage_client=storage,
    )

    return consumer, def_worker, storage, sf, session


class TestFundamentalsConsumerDescriptionChange:
    def test_changed_description_triggers_reembed(self) -> None:
        """Any description found -> refresh_for_entity() always called (hash check delegated to worker)."""
        consumer, def_worker, storage, _sf, _session = _make_consumer()

        storage.get_json = AsyncMock(return_value=_DESCRIPTION_ONLY_PAYLOAD)

        msg = {
            "event_id": str(uuid4()),
            "dataset_type": "fundamentals",
            "instrument_id": _INSTRUMENT_ID,
            "canonical_ref_bucket": "silver",
            "canonical_ref_key": "fundamentals/aapl.json",
        }

        asyncio.run(consumer.process_message(None, msg, {}))

        def_worker.refresh_for_entity.assert_awaited_once()

    def test_unchanged_description_delegates_to_worker(self) -> None:
        """Consumer always delegates to refresh_for_entity; worker handles SHA-256 dedup internally."""
        description = "Stable description, no change."

        consumer, def_worker, storage, _sf, _session = _make_consumer()
        storage.get_json = AsyncMock(return_value={"General": {"Description": description}})

        msg = {
            "event_id": str(uuid4()),
            "dataset_type": "fundamentals",
            "instrument_id": _INSTRUMENT_ID,
            "canonical_ref_bucket": "silver",
            "canonical_ref_key": "fundamentals/aapl.json",
        }

        asyncio.run(consumer.process_message(None, msg, {}))

        # Consumer delegates to worker for ALL descriptions; hash dedup is inside refresh_for_entity.
        def_worker.refresh_for_entity.assert_awaited_once()

    def test_non_fundamentals_event_skipped(self) -> None:
        """dataset_type != 'fundamentals' -> process_message returns early."""
        consumer, def_worker, storage, _sf, _session = _make_consumer()

        msg = {
            "event_id": str(uuid4()),
            "dataset_type": "ohlcv",
            "instrument_id": _INSTRUMENT_ID,
            "canonical_ref_bucket": "silver",
            "canonical_ref_key": "ohlcv/aapl.json",
        }

        asyncio.run(consumer.process_message(None, msg, {}))

        storage.get_json.assert_not_awaited()
        def_worker.refresh_for_entity.assert_not_awaited()

    def test_no_description_in_payload_skips_reembed(self) -> None:
        """Payload has no General.Description -> refresh_for_entity not called."""
        consumer, def_worker, storage, _sf, _session = _make_consumer()
        storage.get_json = AsyncMock(return_value={"General": {}})

        msg = {
            "event_id": str(uuid4()),
            "dataset_type": "fundamentals",
            "instrument_id": _INSTRUMENT_ID,
            "canonical_ref_bucket": "silver",
            "canonical_ref_key": "fundamentals/aapl.json",
        }

        asyncio.run(consumer.process_message(None, msg, {}))

        def_worker.refresh_for_entity.assert_not_awaited()

    def test_storage_error_does_not_raise(self) -> None:
        """Storage failure -> method returns cleanly, refresh_for_entity not called."""
        consumer, def_worker, storage, _sf, _session = _make_consumer()
        storage.get_json = AsyncMock(side_effect=RuntimeError("minio down"))

        msg = {
            "event_id": str(uuid4()),
            "dataset_type": "fundamentals",
            "instrument_id": _INSTRUMENT_ID,
            "canonical_ref_bucket": "silver",
            "canonical_ref_key": "fundamentals/aapl.json",
        }

        asyncio.run(consumer.process_message(None, msg, {}))

        def_worker.refresh_for_entity.assert_not_awaited()

    def test_missing_instrument_id_skips(self) -> None:
        """Missing instrument_id -> returns early without any work."""
        consumer, def_worker, _storage, _sf, _session = _make_consumer()

        msg = {
            "event_id": str(uuid4()),
            "dataset_type": "fundamentals",
            "canonical_ref_bucket": "silver",
            "canonical_ref_key": "fundamentals/unknown.json",
        }

        asyncio.run(consumer.process_message(None, msg, {}))

        def_worker.refresh_for_entity.assert_not_awaited()


class TestFundamentalsConsumerMetadataEnrichment:
    """Wave B-1: structured metadata extraction and entity metadata patch."""

    def test_all_four_fields_produce_update(self) -> None:
        """Full payload with all 4 metadata fields -> update_metadata called with all keys."""
        consumer, _def_worker, storage, _sf, session = _make_consumer()
        storage.get_json = AsyncMock(return_value=_FULL_PAYLOAD)

        msg = {
            "event_id": str(uuid4()),
            "dataset_type": "fundamentals",
            "instrument_id": _INSTRUMENT_ID,
            "canonical_ref_bucket": "silver",
            "canonical_ref_key": "fundamentals/aapl.json",
        }

        with patch(
            "knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer.EntityRepository"
        ) as MockRepo:
            mock_instance = AsyncMock()
            MockRepo.return_value = mock_instance

            asyncio.run(consumer.process_message(None, msg, {}))

        mock_instance.update_metadata.assert_awaited_once()
        _entity_id, updates = mock_instance.update_metadata.call_args.args
        assert updates["employee_count"] == 164000
        assert updates["revenue_ttm_usd"] == 394328000000
        assert updates["pct_insiders"] == pytest.approx(0.07)
        assert updates["pct_institutions"] == pytest.approx(60.52)
        session.commit.assert_awaited()

    def test_partial_fields_only_present_keys_in_update(self) -> None:
        """Payload with only FullTimeEmployees -> update_metadata called with only employee_count."""
        consumer, _def_worker, storage, _sf, _session = _make_consumer()
        payload = {"General": {"FullTimeEmployees": 50000, "Description": "Some corp."}}
        storage.get_json = AsyncMock(return_value=payload)

        msg = {
            "event_id": str(uuid4()),
            "dataset_type": "fundamentals",
            "instrument_id": _INSTRUMENT_ID,
            "canonical_ref_bucket": "silver",
            "canonical_ref_key": "fundamentals/some.json",
        }

        with patch(
            "knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer.EntityRepository"
        ) as MockRepo:
            mock_instance = AsyncMock()
            MockRepo.return_value = mock_instance

            asyncio.run(consumer.process_message(None, msg, {}))

        mock_instance.update_metadata.assert_awaited_once()
        _entity_id, updates = mock_instance.update_metadata.call_args.args
        assert set(updates.keys()) == {"employee_count"}
        assert updates["employee_count"] == 50000

    def test_no_metadata_fields_skips_update(self) -> None:
        """Payload with only Description and no structured fields -> update_metadata NOT called."""
        consumer, def_worker, storage, _sf, session = _make_consumer()
        storage.get_json = AsyncMock(return_value=_DESCRIPTION_ONLY_PAYLOAD)

        msg = {
            "event_id": str(uuid4()),
            "dataset_type": "fundamentals",
            "instrument_id": _INSTRUMENT_ID,
            "canonical_ref_bucket": "silver",
            "canonical_ref_key": "fundamentals/aapl.json",
        }

        with patch(
            "knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer.EntityRepository"
        ) as MockRepo:
            mock_instance = AsyncMock()
            MockRepo.return_value = mock_instance

            asyncio.run(consumer.process_message(None, msg, {}))

        mock_instance.update_metadata.assert_not_awaited()
        session.commit.assert_not_awaited()
        # Description processing still happens
        def_worker.refresh_for_entity.assert_awaited_once()

    def test_metadata_and_description_both_processed(self) -> None:
        """Full payload -> both refresh_for_entity AND update_metadata are called."""
        consumer, def_worker, storage, _sf, _session = _make_consumer()
        storage.get_json = AsyncMock(return_value=_FULL_PAYLOAD)

        msg = {
            "event_id": str(uuid4()),
            "dataset_type": "fundamentals",
            "instrument_id": _INSTRUMENT_ID,
            "canonical_ref_bucket": "silver",
            "canonical_ref_key": "fundamentals/aapl.json",
        }

        with patch(
            "knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer.EntityRepository"
        ) as MockRepo:
            mock_instance = AsyncMock()
            MockRepo.return_value = mock_instance

            asyncio.run(consumer.process_message(None, msg, {}))

        def_worker.refresh_for_entity.assert_awaited_once()
        mock_instance.update_metadata.assert_awaited_once()

    def test_idempotent_same_payload_twice(self) -> None:
        """Same payload processed twice -> update_metadata called both times (DB merge is idempotent)."""
        consumer, _def_worker, storage, _sf, _session = _make_consumer()
        storage.get_json = AsyncMock(return_value=_FULL_PAYLOAD)

        msg = {
            "event_id": str(uuid4()),
            "dataset_type": "fundamentals",
            "instrument_id": _INSTRUMENT_ID,
            "canonical_ref_bucket": "silver",
            "canonical_ref_key": "fundamentals/aapl.json",
        }

        with patch(
            "knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer.EntityRepository"
        ) as MockRepo:
            mock_instance = AsyncMock()
            MockRepo.return_value = mock_instance

            asyncio.run(consumer.process_message(None, msg, {}))
            asyncio.run(consumer.process_message(None, msg, {}))

        # Both calls reach update_metadata; DB JSONB || merge produces identical state (idempotent)
        assert mock_instance.update_metadata.await_count == 2
        first_call_updates = mock_instance.update_metadata.call_args_list[0].args[1]
        second_call_updates = mock_instance.update_metadata.call_args_list[1].args[1]
        assert first_call_updates == second_call_updates

    def test_null_metadata_fields_skipped(self) -> None:
        """Fields with None values (EODHD returns null) are not included in updates."""
        consumer, _def_worker, storage, _sf, _session = _make_consumer()
        payload = {
            "General": {"FullTimeEmployees": None},
            "Highlights": {"RevenueTTM": None},
            "SharesStats": {"PercentInsiders": None, "PercentInstitutions": None},
        }
        storage.get_json = AsyncMock(return_value=payload)

        msg = {
            "event_id": str(uuid4()),
            "dataset_type": "fundamentals",
            "instrument_id": _INSTRUMENT_ID,
            "canonical_ref_bucket": "silver",
            "canonical_ref_key": "fundamentals/null.json",
        }

        with patch(
            "knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer.EntityRepository"
        ) as MockRepo:
            mock_instance = AsyncMock()
            MockRepo.return_value = mock_instance

            asyncio.run(consumer.process_message(None, msg, {}))

        # All fields were None → nothing to update → update_metadata NOT called
        mock_instance.update_metadata.assert_not_awaited()


class TestExtractMetadataUpdates:
    """Unit tests for the module-level _extract_metadata_updates helper."""

    def test_full_payload_all_four_fields(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer import _extract_metadata_updates

        result = _extract_metadata_updates(_FULL_PAYLOAD)
        assert result == {
            "employee_count": 164000,
            "revenue_ttm_usd": 394328000000,
            "pct_insiders": pytest.approx(0.07),
            "pct_institutions": pytest.approx(60.52),
        }

    def test_empty_payload_returns_empty(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer import _extract_metadata_updates

        assert _extract_metadata_updates({}) == {}

    def test_missing_sections_returns_empty(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer import _extract_metadata_updates

        # Only General.Description present — no structured fields
        assert _extract_metadata_updates({"General": {"Description": "foo"}}) == {}

    def test_zero_values_excluded(self) -> None:
        """0 is falsy — fields set to 0 are excluded (EODHD returns 0 for unknown)."""
        from knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer import _extract_metadata_updates

        payload = {
            "General": {"FullTimeEmployees": 0},
            "Highlights": {"RevenueTTM": 0},
        }
        assert _extract_metadata_updates(payload) == {}

    def test_type_coercion_employee_count_is_int(self) -> None:
        """FullTimeEmployees may come as string from EODHD — must be int."""
        from knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer import _extract_metadata_updates

        payload = {"General": {"FullTimeEmployees": "164000"}}
        result = _extract_metadata_updates(payload)
        assert result["employee_count"] == 164000
        assert isinstance(result["employee_count"], int)

    def test_type_coercion_pct_is_float(self) -> None:
        """PercentInsiders comes as float — must remain float."""
        from knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer import _extract_metadata_updates

        payload = {"SharesStats": {"PercentInsiders": "5.23"}}
        result = _extract_metadata_updates(payload)
        assert result["pct_insiders"] == pytest.approx(5.23)
        assert isinstance(result["pct_insiders"], float)
