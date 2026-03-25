"""Reusable service integration contract test base class."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class IntegrationExpectation:
    producer_service: str
    consumer_service: str
    event_topic: str
    expected_latency_ms: int = 5000


class IntegrationContractTestBase:
    """Base class for producer->consumer integration contract checks.

    Subclasses should override the probe hooks to integrate with their test
    infrastructure (Kafka clients, HTTP clients, DB sessions, etc.).
    """

    expectation: IntegrationExpectation

    def trigger_producer_action(self) -> Any:
        raise NotImplementedError

    def wait_for_consumer_effect(self, timeout_ms: int) -> bool:
        raise NotImplementedError

    def assert_envelope_fields(self, event_payload: dict[str, Any]) -> None:
        required = {
            "event_id",
            "event_type",
            "schema_version",
            "occurred_at",
        }
        missing = required - set(event_payload)
        assert not missing, f"Missing envelope fields: {sorted(missing)}"

    def test_integration_contract(self) -> None:
        start = time.monotonic()
        self.trigger_producer_action()

        ok = self.wait_for_consumer_effect(self.expectation.expected_latency_ms)
        assert ok, (
            f"{self.expectation.producer_service}->{self.expectation.consumer_service} "
            f"did not converge on topic {self.expectation.event_topic} "
            f"within {self.expectation.expected_latency_ms}ms"
        )

        elapsed_ms = int((time.monotonic() - start) * 1000)
        assert elapsed_ms <= self.expectation.expected_latency_ms
