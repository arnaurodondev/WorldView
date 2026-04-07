from __future__ import annotations

from typing import ClassVar

import pytest

from tests.contract.templates.avro_contract_test import AvroContractTestBase


@pytest.mark.contract
class TestPortfolioEventContract(AvroContractTestBase):
    schema_file = "infra/kafka/schemas/portfolio.events.v1.avsc"
    valid_samples: ClassVar[list[dict]] = [  # type: ignore[type-arg]
        {
            "event_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9cf",
            "event_type": "portfolio.created",
            "schema_version": 1,
            "occurred_at": "2026-03-24T12:00:00Z",
            "aggregate_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9d0",
            "tenant_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9d1",
            "payload": '{"name": "Core Portfolio"}',
            "correlation_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9d2",
        }
    ]

    def test_invalid_sample_missing_required_field_is_rejected(self) -> None:
        invalid_sample = {
            "event_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9cf",
            "event_type": "portfolio.created",
            "schema_version": 1,
            "occurred_at": "2026-03-24T12:00:00Z",
            "tenant_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9d1",
            "payload": "{}",
            "correlation_id": None,
        }
        with pytest.raises(Exception):  # noqa: B017
            self.assert_invalid_sample_rejected(invalid_sample)
