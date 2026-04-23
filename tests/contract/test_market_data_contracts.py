from __future__ import annotations

from typing import ClassVar

import pytest

from tests.contract.templates.avro_contract_test import AvroContractTestBase


@pytest.mark.contract
class TestMarketDatasetFetchedContract(AvroContractTestBase):
    schema_file = "infra/kafka/schemas/market.dataset.fetched.avsc"
    valid_samples: ClassVar[list[dict]] = [
        {
            "event_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9cf",
            "event_type": "market.dataset.fetched",
            "schema_version": 1,
            "occurred_at": "2026-03-24T12:00:00Z",
            "correlation_id": None,
            "causation_id": None,
            "task_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9d0",
            "provider": "eodhd",
            "dataset_type": "ohlcv",
            "symbol": "AAPL",
            "exchange": "US",
            "timeframe": "1d",
            "variant": None,
            "range_start": "2026-03-01T00:00:00Z",
            "range_end": "2026-03-24T00:00:00Z",
            "bronze_ref_bucket": "market-bronze",
            "bronze_ref_key": "market/data/018f3a85/raw/v1.json",
            "bronze_ref_sha256": "d8f98f1739d9f44ed6d8f7cdbf9f79e7ee4ca2a3522f2b2da6ec4f37a8f16d2b",
            "bronze_ref_byte_length": 1024,
            "bronze_ref_mime_type": "application/json",
            "canonical_ref_bucket": "market-canonical",
            "canonical_ref_key": "market/data/018f3a85/canonical/v1.ndjson",
            "canonical_ref_sha256": "9f8a2b8baf0c87ea056e3ac1b2f11cb0f4c13ca9d11ac65ce66a5f2c33f14479",
            "canonical_ref_byte_length": 2048,
            "canonical_ref_mime_type": "application/x-ndjson",
            "canonical_schema_version": 1,
            "row_count": 120,
        }
    ]

    def test_invalid_sample_wrong_type_is_rejected(self) -> None:
        invalid_sample = {
            **self.valid_samples[0],
            "schema_version": "1",
        }
        with pytest.raises(ValueError):  # fastavro raises ValueError for type mismatches
            self.assert_invalid_sample_rejected(invalid_sample)
