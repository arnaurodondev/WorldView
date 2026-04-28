"""Unit tests for MacroIndicatorDatasetConsumer (Consumer 13D-7).

Replaces the former test_macro_indicator_worker.py.
Tests cover:
- Happy path: valid macro_indicator message → metadata updated + entity.dirtied produced.
- Filter: non-macro_indicator dataset_type silently skipped.
- Hash guard: no update when data is unchanged.
- Symbol parsing: indicator code + ISO3 country extracted correctly.
  Symbol format is ``ISO3.indicator_code`` (e.g. "USA.gdp_current_usd").
- ISO3 → ISO2 mapping.
- Missing country entity: returns early, no update.
- Empty payload: no DB calls.
- Storage failure: transient errors re-raised; JSON decode errors skipped.
- Prometheus counter.
- Producer called with correct topic + payload.
- _sha256_hex and _parse_symbol helpers.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

_COUNTRY_ENTITY_ID = UUID("01910000-0000-7000-8000-000000000001")

_ENTITY_REPO = "knowledge_graph.infrastructure.intelligence_db.repositories.entity_repository.EntityRepository"

# Minimal EODHD macro indicator payload (sorted date descending — index 0 is most recent)
_GDP_PAYLOAD = [{"Value": 25_000_000_000_000.0, "Period": "2023"}]
_INFLATION_PAYLOAD = [{"Value": 3.4, "Period": "2023"}]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_consumer(
    country_entity_id: UUID | None = _COUNTRY_ENTITY_ID,
    stored_macro_data: dict[str, Any] | None = None,
    old_hash: str | None = None,
    direct_producer: Any = None,
    storage_bytes: bytes | None = None,
    storage_error: Exception | None = None,
) -> tuple[Any, Any, Any]:
    """Build MacroIndicatorDatasetConsumer with mocked dependencies.

    Returns:
        (consumer, entity_repo_mock, session_mock)
    """
    from knowledge_graph.infrastructure.messaging.consumers.macro_indicator_dataset_consumer import (
        MacroIndicatorDatasetConsumer,
    )

    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="kg-macro-indicator-test",
        topics=["market.dataset.fetched"],
    )

    # Session factory mock
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    sf = MagicMock()
    sf.return_value = session

    # Storage client mock
    storage = AsyncMock()
    if storage_error is not None:
        storage.get_bytes = AsyncMock(side_effect=storage_error)
    elif storage_bytes is not None:
        storage.get_bytes = AsyncMock(return_value=storage_bytes)

    # Entity repo mock
    entity_repo = AsyncMock()
    entity_repo.find_country_entity = AsyncMock(return_value=country_entity_id)
    entity_repo.get_metadata_hash = AsyncMock(return_value=old_hash)
    entity_repo.get_metadata_field = AsyncMock(return_value=stored_macro_data or {})
    entity_repo.update_metadata = AsyncMock()

    consumer = MacroIndicatorDatasetConsumer(
        config=config,
        session_factory=sf,
        storage_client=storage,
        direct_producer=direct_producer,
        entity_dirtied_topic="entity.dirtied.v1",
    )

    return consumer, entity_repo, session


def _make_envelope(payload: list[dict[str, Any]], dataset_type: str, symbol: str) -> bytes:
    """Build canonical NDJSON envelope bytes."""
    envelope = {
        "dataset_type": dataset_type,
        "symbol": symbol,
        "source": "eodhd",
        "payload": payload,
        "fetched_at": "2026-04-07T06:00:00+00:00",
    }
    return (json.dumps(envelope) + "\n").encode("utf-8")


def _make_message(
    symbol: str = "USA.gdp_current_usd",  # Real S2 format: ISO3.indicator_code
    dataset_type: str = "macro_indicator",
    bucket: str = "canonical",
    key: str = "macro_indicator/usa/gdp_current_usd.ndjson",
) -> dict[str, Any]:
    """Build a decoded Avro dict for market.dataset.fetched."""
    return {
        "event_id": str(uuid4()),
        "dataset_type": dataset_type,
        "symbol": symbol,
        "canonical_ref_bucket": bucket,
        "canonical_ref_key": key,
    }


# ── Test: filter by dataset_type ─────────────────────────────────────────────


class TestMacroIndicatorConsumerFilter:
    def test_non_macro_type_skipped(self) -> None:
        """dataset_type != 'macro_indicator' → process_message returns early."""
        consumer, entity_repo, _ = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=b"")

        msg = _make_message(dataset_type="economic_events")
        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(consumer.process_message(None, msg, {}))

        consumer._storage.get_bytes.assert_not_awaited()
        entity_repo.update_metadata.assert_not_awaited()

    def test_ohlcv_type_skipped(self) -> None:
        """dataset_type='ohlcv' → skipped."""
        consumer, entity_repo, _ = _make_consumer()
        msg = _make_message(dataset_type="ohlcv")
        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(consumer.process_message(None, msg, {}))
        entity_repo.update_metadata.assert_not_awaited()


# ── Test: happy path ──────────────────────────────────────────────────────────


class TestMacroIndicatorConsumerHappyPath:
    def test_new_indicator_updates_metadata(self) -> None:
        """New indicator data (hash mismatch) → update_metadata called with merged dict."""
        producer = MagicMock()
        consumer, entity_repo, _ = _make_consumer(
            old_hash=None,  # No existing hash → always triggers update
            direct_producer=producer,
        )
        consumer._storage.get_bytes = AsyncMock(
            return_value=_make_envelope(_GDP_PAYLOAD, "macro_indicator", "USA.gdp_current_usd")
        )

        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        entity_repo.update_metadata.assert_awaited_once()
        call_args = entity_repo.update_metadata.call_args[0]
        assert call_args[0] == _COUNTRY_ENTITY_ID
        updates = call_args[1]
        assert "macro_indicators" in updates
        macro = updates["macro_indicators"]
        assert "gdp_current_usd" in macro
        assert macro["gdp_current_usd"]["value"] == 25e12
        assert macro["gdp_current_usd"]["year"] == "2023"

    def test_entity_dirtied_produced_on_update(self) -> None:
        """entity.dirtied.v1 produced when metadata is updated."""
        producer = MagicMock()
        consumer, entity_repo, _ = _make_consumer(old_hash=None, direct_producer=producer)
        consumer._storage.get_bytes = AsyncMock(
            return_value=_make_envelope(_GDP_PAYLOAD, "macro_indicator", "USA.gdp_current_usd")
        )

        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        producer.produce_bytes.assert_called_once()
        call_kwargs = producer.produce_bytes.call_args.kwargs
        assert call_kwargs["topic"] == "entity.dirtied.v1"
        assert call_kwargs["key"] == str(_COUNTRY_ENTITY_ID).encode()
        payload = json.loads(call_kwargs["value"])
        assert payload["entity_id"] == str(_COUNTRY_ENTITY_ID)
        assert payload["dirty_reason"] == "macro_indicators_updated"

    def test_session_committed_after_update(self) -> None:
        """session.commit() called when metadata is updated."""
        consumer, entity_repo, session = _make_consumer(old_hash=None)
        consumer._storage.get_bytes = AsyncMock(
            return_value=_make_envelope(_GDP_PAYLOAD, "macro_indicator", "USA.gdp_current_usd")
        )

        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        session.commit.assert_awaited_once()


# ── Test: hash guard (no change) ──────────────────────────────────────────────


class TestMacroIndicatorConsumerNoChange:
    def test_no_update_when_hash_matches(self) -> None:
        """Same indicator data → hash matches → update_metadata NOT called."""
        from knowledge_graph.infrastructure.messaging.consumers.macro_indicator_dataset_consumer import (
            _sha256_hex,
        )

        merged = {"gdp_current_usd": {"value": 25e12, "year": "2023"}}
        existing_hash = _sha256_hex(json.dumps(merged, sort_keys=True))

        producer = MagicMock()
        consumer, entity_repo, session = _make_consumer(
            old_hash=existing_hash,
            stored_macro_data=merged,
            direct_producer=producer,
        )
        consumer._storage.get_bytes = AsyncMock(
            return_value=_make_envelope(_GDP_PAYLOAD, "macro_indicator", "USA.gdp_current_usd")
        )

        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        entity_repo.update_metadata.assert_not_awaited()
        producer.produce_bytes.assert_not_called()
        session.commit.assert_not_awaited()


# ── Test: symbol parsing ──────────────────────────────────────────────────────


class TestParseSymbol:
    def test_standard_symbol_parsed(self) -> None:
        """S2 sends "ISO3.indicator_code" — country comes first."""
        from knowledge_graph.infrastructure.messaging.consumers.macro_indicator_dataset_consumer import (
            _parse_symbol,
        )

        code, iso3 = _parse_symbol("USA.gdp_current_usd")
        assert code == "gdp_current_usd"
        assert iso3 == "USA"

    def test_eur_symbol_parsed(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.macro_indicator_dataset_consumer import (
            _parse_symbol,
        )

        code, iso3 = _parse_symbol("EUR.inflation_consumer_prices_annual")
        assert code == "inflation_consumer_prices_annual"
        assert iso3 == "EUR"

    def test_indicator_code_normalised_to_lower(self) -> None:
        """Indicator portion is lower-cased; country preserved as-is."""
        from knowledge_graph.infrastructure.messaging.consumers.macro_indicator_dataset_consumer import (
            _parse_symbol,
        )

        code, iso3 = _parse_symbol("USA.GDPCAP")
        assert code == "gdpcap"
        assert iso3 == "USA"

    def test_no_dot_returns_full_symbol(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.macro_indicator_dataset_consumer import (
            _parse_symbol,
        )

        code, iso3 = _parse_symbol("NODOTSYMBOL")
        assert code == "nodotsymbol"
        assert iso3 == ""

    def test_gbr_symbol_parsed(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.macro_indicator_dataset_consumer import (
            _parse_symbol,
        )

        code, iso3 = _parse_symbol("GBR.current_account_balance_bop_usd")
        assert code == "current_account_balance_bop_usd"
        assert iso3 == "GBR"


# ── Test: ISO3 → ISO2 mapping ─────────────────────────────────────────────────


class TestMacroIndicatorConsumerIso3Mapping:
    def test_usa_mapped_to_us(self) -> None:
        """USA → US mapping used for entity lookup."""
        consumer, entity_repo, _ = _make_consumer(old_hash=None)
        consumer._storage.get_bytes = AsyncMock(
            return_value=_make_envelope(_GDP_PAYLOAD, "macro_indicator", "USA.gdp_current_usd")
        )

        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(consumer.process_message(None, _make_message(symbol="USA.gdp_current_usd"), {}))

        entity_repo.find_country_entity.assert_awaited_once_with("US")

    def test_gbr_mapped_to_gb(self) -> None:
        consumer, entity_repo, _ = _make_consumer(old_hash=None)
        consumer._storage.get_bytes = AsyncMock(
            return_value=_make_envelope(_GDP_PAYLOAD, "macro_indicator", "GBR.gdp_current_usd")
        )

        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(
                consumer.process_message(
                    None,
                    _make_message(symbol="GBR.gdp_current_usd", key="macro_indicator/gbr/gdp.ndjson"),
                    {},
                )
            )

        entity_repo.find_country_entity.assert_awaited_once_with("GB")

    def test_unknown_iso3_falls_back_to_first_two_chars(self) -> None:
        """Unknown ISO3 code falls back to first 2 chars for entity lookup."""
        consumer, entity_repo, _ = _make_consumer(old_hash=None)
        consumer._storage.get_bytes = AsyncMock(
            return_value=_make_envelope(_GDP_PAYLOAD, "macro_indicator", "ZAF.gdp_current_usd")
        )

        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(consumer.process_message(None, _make_message(symbol="ZAF.gdp_current_usd"), {}))

        entity_repo.find_country_entity.assert_awaited_once_with("ZA")


# ── Test: missing country entity ──────────────────────────────────────────────


class TestMacroIndicatorConsumerMissingCountry:
    def test_skip_when_country_entity_not_found(self) -> None:
        """find_country_entity returns None → update skipped, no entity.dirtied."""
        producer = MagicMock()
        consumer, entity_repo, session = _make_consumer(
            country_entity_id=None,
            old_hash=None,
            direct_producer=producer,
        )
        consumer._storage.get_bytes = AsyncMock(
            return_value=_make_envelope(_GDP_PAYLOAD, "macro_indicator", "USA.gdp_current_usd")
        )

        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        entity_repo.update_metadata.assert_not_awaited()
        producer.produce_bytes.assert_not_called()
        session.commit.assert_not_awaited()


# ── Test: empty payload ───────────────────────────────────────────────────────


class TestMacroIndicatorConsumerEmptyPayload:
    def test_empty_payload_list_no_db_calls(self) -> None:
        """Empty payload list → no DB calls."""
        consumer, entity_repo, _ = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(
            return_value=_make_envelope([], "macro_indicator", "USA.gdp_current_usd")
        )

        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        entity_repo.find_country_entity.assert_not_awaited()
        entity_repo.update_metadata.assert_not_awaited()

    def test_unparseable_symbol_no_db_calls(self) -> None:
        """Symbol with no dot → unparseable → no DB calls."""
        consumer, entity_repo, _ = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(
            return_value=_make_envelope(_GDP_PAYLOAD, "macro_indicator", "NODOTSYMBOL")
        )

        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(
                consumer.process_message(
                    None,
                    _make_message(symbol="NODOTSYMBOL"),
                    {},
                )
            )

        entity_repo.find_country_entity.assert_not_awaited()


# ── Test: storage failure ─────────────────────────────────────────────────────


class TestMacroIndicatorConsumerStorageError:
    def test_transient_storage_exception_propagates(self) -> None:
        """Transient storage error (e.g. network) re-raised so offset is NOT committed."""
        consumer, entity_repo, _ = _make_consumer(storage_error=RuntimeError("minio down"))

        with patch(_ENTITY_REPO, return_value=entity_repo):
            with pytest.raises(RuntimeError, match="minio down"):
                asyncio.run(consumer.process_message(None, _make_message(), {}))

        entity_repo.update_metadata.assert_not_awaited()

    def test_malformed_json_skipped_gracefully(self) -> None:
        """JSON decode error (bad envelope) → skipped without raise."""
        import json as json_mod

        consumer, entity_repo, _ = _make_consumer(storage_error=json_mod.JSONDecodeError("bad json", "", 0))

        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        entity_repo.update_metadata.assert_not_awaited()


# ── Test: no direct producer ──────────────────────────────────────────────────


class TestMacroIndicatorConsumerNoProducer:
    def test_update_without_producer_does_not_crash(self) -> None:
        """Update proceeds even without a direct_producer configured."""
        consumer, entity_repo, _ = _make_consumer(old_hash=None, direct_producer=None)
        consumer._storage.get_bytes = AsyncMock(
            return_value=_make_envelope(_GDP_PAYLOAD, "macro_indicator", "USA.gdp_current_usd")
        )

        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        entity_repo.update_metadata.assert_awaited_once()


# ── Test: Prometheus counter ──────────────────────────────────────────────────


class TestMacroIndicatorConsumerPrometheus:
    def test_counter_incremented_on_update(self) -> None:
        """s7_macro_indicator_updates_total{country='US'} incremented on change."""
        from knowledge_graph.infrastructure.metrics.prometheus import s7_macro_indicator_updates_total

        consumer, entity_repo, _ = _make_consumer(old_hash=None)
        consumer._storage.get_bytes = AsyncMock(
            return_value=_make_envelope(_GDP_PAYLOAD, "macro_indicator", "USA.gdp_current_usd")
        )

        before = s7_macro_indicator_updates_total.labels(country="US")._value.get()
        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(consumer.process_message(None, _make_message(), {}))
        after = s7_macro_indicator_updates_total.labels(country="US")._value.get()

        assert after - before == 1.0

    def test_counter_not_incremented_on_no_change(self) -> None:
        """Counter not incremented when hash matches (no update)."""
        from knowledge_graph.infrastructure.messaging.consumers.macro_indicator_dataset_consumer import (
            _sha256_hex,
        )
        from knowledge_graph.infrastructure.metrics.prometheus import s7_macro_indicator_updates_total

        merged = {"gdp_current_usd": {"value": 25e12, "year": "2023"}}
        existing_hash = _sha256_hex(json.dumps(merged, sort_keys=True))

        consumer, entity_repo, _ = _make_consumer(old_hash=existing_hash, stored_macro_data=merged)
        consumer._storage.get_bytes = AsyncMock(
            return_value=_make_envelope(_GDP_PAYLOAD, "macro_indicator", "USA.gdp_current_usd")
        )

        before = s7_macro_indicator_updates_total.labels(country="US")._value.get()
        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(consumer.process_message(None, _make_message(), {}))
        after = s7_macro_indicator_updates_total.labels(country="US")._value.get()

        assert after == before


# ── Test: _sha256_hex helper ──────────────────────────────────────────────────


class TestSha256HexHelper:
    def test_returns_64_char_hex_string(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.macro_indicator_dataset_consumer import (
            _sha256_hex,
        )

        result = _sha256_hex("test")
        assert isinstance(result, str)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.macro_indicator_dataset_consumer import (
            _sha256_hex,
        )

        assert _sha256_hex("hello") == _sha256_hex("hello")

    def test_different_inputs_different_hashes(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.macro_indicator_dataset_consumer import (
            _sha256_hex,
        )

        assert _sha256_hex('{"a": 1}') != _sha256_hex('{"a": 2}')
