"""Unit tests for the base adapter and shared utilities."""

from __future__ import annotations

import pytest
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.adapters.base import RetryConfig, SourceAdapter, url_hash

pytestmark = pytest.mark.unit


class TestUrlHash:
    def test_returns_sha256_hex(self) -> None:
        result = url_hash("https://example.com/article/1")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self) -> None:
        assert url_hash("same-input") == url_hash("same-input")

    def test_different_inputs_different_hashes(self) -> None:
        assert url_hash("input-a") != url_hash("input-b")


class TestRetryRequest:
    async def test_succeeds_on_first_attempt(self) -> None:
        call_count = 0

        async def succeeding() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await SourceAdapter._retry_request(succeeding, context="test")
        assert result == "ok"
        assert call_count == 1

    async def test_retries_on_failure_then_succeeds(self) -> None:
        call_count = 0

        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                msg = "transient"
                raise RuntimeError(msg)
            return "recovered"

        cfg = RetryConfig(max_retries=3, backoff_factors=(0.0, 0.0, 0.0))
        result = await SourceAdapter._retry_request(flaky, retry_config=cfg, context="test")
        assert result == "recovered"
        assert call_count == 3

    async def test_raises_after_all_retries_exhausted(self) -> None:
        async def always_fail() -> None:
            msg = "permanent"
            raise RuntimeError(msg)

        cfg = RetryConfig(max_retries=2, backoff_factors=(0.0, 0.0))
        with pytest.raises(AdapterError, match="All 2 retries exhausted"):
            await SourceAdapter._retry_request(always_fail, retry_config=cfg, context="test")

    async def test_uses_backoff_factors(self) -> None:
        """Verify the retry count matches max_retries + 1 total attempts."""
        attempts: list[int] = []

        async def counting_fail() -> None:
            attempts.append(1)
            msg = "fail"
            raise RuntimeError(msg)

        cfg = RetryConfig(max_retries=3, backoff_factors=(0.0, 0.0, 0.0))
        with pytest.raises(AdapterError):
            await SourceAdapter._retry_request(counting_fail, retry_config=cfg, context="test")
        assert len(attempts) == 4  # 1 initial + 3 retries
