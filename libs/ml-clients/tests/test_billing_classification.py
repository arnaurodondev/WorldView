"""HTTP-status classification: spend-cap / auth refusals must be RETRYABLE (2026-07-18).

Regression guard for the DeepInfra spend-cap incident: an HTTP 402 ``Payment
Required`` (and 401/403 auth refusals) were mis-classified as fatal 4xx, so
extraction silently empty-committed and embeddings were abandoned. Both must now
surface :class:`ProviderBillingError` (a RetryableError) while a genuine bad-input
4xx (400/404/413/422) stays fatal and 5xx / 429 keep their transient classes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from ml_clients.dataclasses import EmbeddingInput
from ml_clients.errors import (
    FatalError,
    ProviderBillingError,
    RateLimitError,
    RetryableError,
    is_billing_status,
    is_transient_status,
)

# ── Pure helpers ──────────────────────────────────────────────────────────────


class TestStatusHelpers:
    @pytest.mark.parametrize("status", [401, 402, 403])
    def test_billing_statuses(self, status: int) -> None:
        assert is_billing_status(status) is True

    @pytest.mark.parametrize("status", [400, 404, 413, 422, 429, 500])
    def test_non_billing_statuses(self, status: int) -> None:
        assert is_billing_status(status) is False

    @pytest.mark.parametrize("status", [408, 409, 425, 429, 500, 502, 503])
    def test_transient_statuses(self, status: int) -> None:
        assert is_transient_status(status) is True

    @pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 413, 422])
    def test_non_transient_statuses(self, status: int) -> None:
        assert is_transient_status(status) is False

    def test_billing_is_a_retryable_error(self) -> None:
        # A RetryableError subclass so existing except-RetryableError loops
        # (Kafka redelivery, the embedding retry worker) pick it up unchanged.
        assert issubclass(ProviderBillingError, RetryableError)


# ── DeepInfra embedding adapter ───────────────────────────────────────────────


@pytest.mark.asyncio
class TestDeepInfraEmbeddingClassification:
    @pytest.fixture
    def adapter(self):  # type: ignore[no-untyped-def]
        from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter

        return DeepInfraEmbeddingAdapter(api_key="test-key", model_id="BAAI/bge-large-en-v1.5")

    @pytest.fixture
    def inputs(self) -> list[EmbeddingInput]:
        return [EmbeddingInput(text="Apple Inc.", model_id="BAAI/bge-large-en-v1.5")]

    def _patch_status(self, status_code: int):  # type: ignore[no-untyped-def]
        """Return a patch context whose httpx.AsyncClient.post raises HTTPStatusError."""
        resp = MagicMock(status_code=status_code, headers={})
        err = httpx.HTTPStatusError(message=str(status_code), request=MagicMock(), response=resp)
        ctx = patch("httpx.AsyncClient")
        return ctx, err

    async def _run(self, adapter, inputs, status_code: int):  # type: ignore[no-untyped-def]
        ctx, err = self._patch_status(status_code)
        with ctx as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=err)
            await adapter.embed(inputs)

    @pytest.mark.parametrize("status_code", [401, 402, 403])
    async def test_billing_refusal_raises_provider_billing_error(self, adapter, inputs, status_code) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(ProviderBillingError, match="billing/auth refusal"):
            await self._run(adapter, inputs, status_code)

    async def test_rate_limit_raises_rate_limit_error(self, adapter, inputs) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(RateLimitError):
            await self._run(adapter, inputs, 429)

    async def test_5xx_raises_retryable(self, adapter, inputs) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(RetryableError, match="transient"):
            await self._run(adapter, inputs, 503)

    @pytest.mark.parametrize("status_code", [400, 404, 413, 422])
    async def test_bad_input_4xx_raises_fatal(self, adapter, inputs, status_code) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(FatalError, match="4xx"):
            await self._run(adapter, inputs, status_code)


# ── DeepSeek extraction adapter classification (_classify_transient) ──────────


class TestDeepSeekExtractionClassification:
    """``_classify_transient`` maps a provider APIStatusError to the right typed error.

    We build a fake ``openai`` module namespace on the adapter so we can exercise
    the branch without the real SDK, mirroring the adapter's ``self._openai`` usage.
    """

    def _make_adapter_with_fake_openai(self):  # type: ignore[no-untyped-def]
        from ml_clients.adapters.deepseek_extraction import DeepSeekExtractionAdapter

        # Build a minimal fake openai namespace with the exception classes the
        # classifier isinstance-checks. Only APIStatusError matters here.
        class _APIStatusError(Exception):
            def __init__(self, message: str, status_code: int) -> None:
                super().__init__(message)
                self.status_code = status_code

        class _RateLimitError(_APIStatusError):
            pass

        class _APITimeoutError(Exception):
            pass

        class _APIConnectionError(Exception):
            pass

        fake_openai = MagicMock()
        fake_openai.APIStatusError = _APIStatusError
        fake_openai.RateLimitError = _RateLimitError
        fake_openai.APITimeoutError = _APITimeoutError
        fake_openai.APIConnectionError = _APIConnectionError

        adapter = DeepSeekExtractionAdapter.__new__(DeepSeekExtractionAdapter)
        adapter._openai = fake_openai
        adapter._timeout_s = 60.0
        return adapter, _APIStatusError

    @pytest.mark.parametrize("status_code", [401, 402, 403])
    def test_billing_refusal_maps_to_provider_billing_error(self, status_code) -> None:  # type: ignore[no-untyped-def]
        adapter, api_status_error = self._make_adapter_with_fake_openai()
        mapped = adapter._classify_transient(api_status_error("boom", status_code))
        assert isinstance(mapped, ProviderBillingError)

    def test_5xx_maps_to_retryable(self) -> None:
        adapter, api_status_error = self._make_adapter_with_fake_openai()
        mapped = adapter._classify_transient(api_status_error("boom", 503))
        assert isinstance(mapped, RetryableError)
        assert not isinstance(mapped, ProviderBillingError)

    @pytest.mark.parametrize("status_code", [400, 404, 413, 422])
    def test_bad_input_4xx_maps_to_fatal(self, status_code) -> None:  # type: ignore[no-untyped-def]
        adapter, api_status_error = self._make_adapter_with_fake_openai()
        mapped = adapter._classify_transient(api_status_error("boom", status_code))
        assert isinstance(mapped, FatalError)
