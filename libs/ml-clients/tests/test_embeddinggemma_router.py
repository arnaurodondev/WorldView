"""Unit tests for EmbeddingGemmaRouterAdapter (PLAN-0111 C-1).

All HTTP calls are mocked. Live behaviour was separately smoke-tested against
DeepInfra (768d, ~0.32s, finance/sports cosine sanity) during implementation.
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ml_clients.adapters.embeddinggemma_router import (
    _CLASSIFICATION_PREFIX,
    EmbeddingGemmaRouterAdapter,
)
from ml_clients.errors import FatalError, RateLimitError, RetryableError


def _make_response(embeddings: list[list[float]]) -> MagicMock:
    """Build a mock httpx response shaped like DeepInfra's OpenAI embeddings API."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "object": "list",
        "model": "google/embeddinggemma-300m",
        "data": [{"embedding": emb, "index": i} for i, emb in enumerate(embeddings)],
    }
    return mock_resp


def _native_vec(seed: float = 0.1) -> list[float]:
    """A deterministic 768-d vector (native EmbeddingGemma dimension)."""
    return [seed] * 768


class TestEmbeddingGemmaRouterAdapter:
    # ── construction ───────────────────────────────────────────────────────
    def test_invalid_default_dimensions_rejected(self) -> None:
        with pytest.raises(ValueError, match="MRL cut point"):
            EmbeddingGemmaRouterAdapter(api_key="k", default_dimensions=300)

    def test_timeout_wrapped_in_httpx_timeout(self) -> None:
        """BP-235: the float timeout must be wrapped in an explicit httpx.Timeout."""
        import httpx

        adapter = EmbeddingGemmaRouterAdapter(api_key="k", timeout=12.0)
        assert isinstance(adapter._timeout, httpx.Timeout)

    # ── empty input ────────────────────────────────────────────────────────
    async def test_empty_input_returns_empty_without_http(self) -> None:
        adapter = EmbeddingGemmaRouterAdapter(api_key="k")
        assert await adapter.embed_for_classification([]) == []

    # ── classification prompt prefix ───────────────────────────────────────
    async def test_classification_prefix_applied(self) -> None:
        """Each input is prefixed with `task: classification | query: `."""
        captured: list[dict] = []

        async def _post(url: str, *, headers: dict, json: dict, **kwargs: object) -> MagicMock:
            captured.append(json)
            return _make_response([_native_vec(), _native_vec()])

        with patch("httpx.AsyncClient") as cls:
            client = AsyncMock()
            cls.return_value.__aenter__ = AsyncMock(return_value=client)
            cls.return_value.__aexit__ = AsyncMock(return_value=False)
            client.post = _post

            adapter = EmbeddingGemmaRouterAdapter(api_key="k")
            await adapter.embed_for_classification(["Apple beats estimates", "Fed hikes rates"])

        sent = captured[0]["input"]
        assert sent[0] == f"{_CLASSIFICATION_PREFIX}Apple beats estimates"
        assert sent[1] == f"{_CLASSIFICATION_PREFIX}Fed hikes rates"
        # bfloat16 model → must request float, not float16.
        assert captured[0]["encoding_format"] == "float"

    # ── document prompt prefix ─────────────────────────────────────────────
    async def test_document_prefix_applied(self) -> None:
        captured: list[dict] = []

        async def _post(url: str, *, headers: dict, json: dict, **kwargs: object) -> MagicMock:
            captured.append(json)
            return _make_response([_native_vec()])

        with patch("httpx.AsyncClient") as cls:
            client = AsyncMock()
            cls.return_value.__aenter__ = AsyncMock(return_value=client)
            cls.return_value.__aexit__ = AsyncMock(return_value=False)
            client.post = _post

            adapter = EmbeddingGemmaRouterAdapter(api_key="k")
            await adapter.embed_documents([("Earnings", "Apple reported Q3 results")])

        assert captured[0]["input"][0] == "title: Earnings | text: Apple reported Q3 results"

    # ── happy path / native dim ────────────────────────────────────────────
    async def test_happy_path_returns_768d(self) -> None:
        with patch("httpx.AsyncClient") as cls:
            client = AsyncMock()
            cls.return_value.__aenter__ = AsyncMock(return_value=client)
            cls.return_value.__aexit__ = AsyncMock(return_value=False)
            client.post = AsyncMock(return_value=_make_response([_native_vec()]))

            adapter = EmbeddingGemmaRouterAdapter(api_key="k")
            out = await adapter.embed_for_classification(["headline"])

        assert len(out) == 1
        assert len(out[0]) == 768

    async def test_batch_preserves_input_order(self) -> None:
        """Out-of-order `index` fields in the response are re-sorted to input order."""
        unordered = MagicMock()
        unordered.raise_for_status = MagicMock()
        unordered.json.return_value = {
            "data": [
                {"embedding": [0.2] * 768, "index": 1},
                {"embedding": [0.1] * 768, "index": 0},
            ]
        }
        with patch("httpx.AsyncClient") as cls:
            client = AsyncMock()
            cls.return_value.__aenter__ = AsyncMock(return_value=client)
            cls.return_value.__aexit__ = AsyncMock(return_value=False)
            client.post = AsyncMock(return_value=unordered)

            adapter = EmbeddingGemmaRouterAdapter(api_key="k")
            out = await adapter.embed_for_classification(["a", "b"])

        assert out[0][0] == pytest.approx(0.1)
        assert out[1][0] == pytest.approx(0.2)

    # ── MRL truncation + renormalization ───────────────────────────────────
    async def test_mrl_truncation_produces_unit_norm_256d(self) -> None:
        """dimensions=256 → 256-d vector that is L2-renormalized to unit norm."""
        with patch("httpx.AsyncClient") as cls:
            client = AsyncMock()
            cls.return_value.__aenter__ = AsyncMock(return_value=client)
            cls.return_value.__aexit__ = AsyncMock(return_value=False)
            client.post = AsyncMock(return_value=_make_response([_native_vec(0.05)]))

            adapter = EmbeddingGemmaRouterAdapter(api_key="k", default_dimensions=256)
            out = await adapter.embed_for_classification(["headline"])

        assert len(out[0]) == 256
        norm = math.sqrt(sum(c * c for c in out[0]))
        assert norm == pytest.approx(1.0, abs=1e-9)

    async def test_per_call_dimensions_override(self) -> None:
        with patch("httpx.AsyncClient") as cls:
            client = AsyncMock()
            cls.return_value.__aenter__ = AsyncMock(return_value=client)
            cls.return_value.__aexit__ = AsyncMock(return_value=False)
            client.post = AsyncMock(return_value=_make_response([_native_vec()]))

            adapter = EmbeddingGemmaRouterAdapter(api_key="k", default_dimensions=768)
            out = await adapter.embed_for_classification(["headline"], dimensions=128)

        assert len(out[0]) == 128
        assert math.sqrt(sum(c * c for c in out[0])) == pytest.approx(1.0, abs=1e-9)

    async def test_invalid_per_call_dimensions_raises_fatal(self) -> None:
        adapter = EmbeddingGemmaRouterAdapter(api_key="k")
        with pytest.raises(FatalError, match="MRL cut point"):
            await adapter.embed_for_classification(["x"], dimensions=300)

    # ── error paths ────────────────────────────────────────────────────────
    async def test_wrong_native_dimension_raises_fatal(self) -> None:
        with patch("httpx.AsyncClient") as cls:
            client = AsyncMock()
            cls.return_value.__aenter__ = AsyncMock(return_value=client)
            cls.return_value.__aexit__ = AsyncMock(return_value=False)
            client.post = AsyncMock(return_value=_make_response([[0.1] * 512]))  # wrong

            adapter = EmbeddingGemmaRouterAdapter(api_key="k")
            with pytest.raises(FatalError, match="dimension"):
                await adapter.embed_for_classification(["x"])

    async def test_result_count_mismatch_raises_fatal(self) -> None:
        with patch("httpx.AsyncClient") as cls:
            client = AsyncMock()
            cls.return_value.__aenter__ = AsyncMock(return_value=client)
            cls.return_value.__aexit__ = AsyncMock(return_value=False)
            client.post = AsyncMock(return_value=_make_response([_native_vec()]))  # 1 result

            adapter = EmbeddingGemmaRouterAdapter(api_key="k")
            with pytest.raises(FatalError):
                await adapter.embed_for_classification(["a", "b"])

    async def test_timeout_raises_retryable(self) -> None:
        import httpx

        with patch("httpx.AsyncClient") as cls:
            client = AsyncMock()
            cls.return_value.__aenter__ = AsyncMock(return_value=client)
            cls.return_value.__aexit__ = AsyncMock(return_value=False)
            client.post.side_effect = httpx.TimeoutException("read timeout")

            adapter = EmbeddingGemmaRouterAdapter(api_key="k")
            with pytest.raises(RetryableError, match="timeout"):
                await adapter.embed_for_classification(["x"])

    async def test_5xx_raises_retryable(self) -> None:
        import httpx

        with patch("httpx.AsyncClient") as cls:
            client = AsyncMock()
            cls.return_value.__aenter__ = AsyncMock(return_value=client)
            cls.return_value.__aexit__ = AsyncMock(return_value=False)
            err = MagicMock(status_code=503, headers={})
            client.post.side_effect = httpx.HTTPStatusError("503", request=MagicMock(), response=err)

            adapter = EmbeddingGemmaRouterAdapter(api_key="k")
            with pytest.raises(RetryableError, match="5xx"):
                await adapter.embed_for_classification(["x"])

    async def test_4xx_raises_fatal(self) -> None:
        import httpx

        with patch("httpx.AsyncClient") as cls:
            client = AsyncMock()
            cls.return_value.__aenter__ = AsyncMock(return_value=client)
            cls.return_value.__aexit__ = AsyncMock(return_value=False)
            err = MagicMock(status_code=401, headers={})
            client.post.side_effect = httpx.HTTPStatusError("401", request=MagicMock(), response=err)

            adapter = EmbeddingGemmaRouterAdapter(api_key="bad")
            with pytest.raises(FatalError, match="4xx"):
                await adapter.embed_for_classification(["x"])

    async def test_429_raises_rate_limit_error_with_retry_after(self) -> None:
        import httpx

        with patch("httpx.AsyncClient") as cls:
            client = AsyncMock()
            cls.return_value.__aenter__ = AsyncMock(return_value=client)
            cls.return_value.__aexit__ = AsyncMock(return_value=False)
            err = MagicMock(status_code=429, headers={"Retry-After": "7"})
            client.post.side_effect = httpx.HTTPStatusError("429", request=MagicMock(), response=err)

            adapter = EmbeddingGemmaRouterAdapter(api_key="k")
            with pytest.raises(RateLimitError) as exc:
                await adapter.embed_for_classification(["x"])

        assert isinstance(exc.value, RetryableError)
        assert not isinstance(exc.value, FatalError)
        assert exc.value.retry_after == 7

    async def test_network_error_raises_retryable(self) -> None:
        import httpx

        with patch("httpx.AsyncClient") as cls:
            client = AsyncMock()
            cls.return_value.__aenter__ = AsyncMock(return_value=client)
            cls.return_value.__aexit__ = AsyncMock(return_value=False)
            client.post.side_effect = httpx.ConnectError("dns failure")

            adapter = EmbeddingGemmaRouterAdapter(api_key="k")
            with pytest.raises(RetryableError, match="network"):
                await adapter.embed_for_classification(["x"])

    async def test_bearer_auth_header_sent(self) -> None:
        captured: list[dict] = []

        async def _post(url: str, *, headers: dict, json: dict, **kwargs: object) -> MagicMock:
            captured.append(headers)
            return _make_response([_native_vec()])

        with patch("httpx.AsyncClient") as cls:
            client = AsyncMock()
            cls.return_value.__aenter__ = AsyncMock(return_value=client)
            cls.return_value.__aexit__ = AsyncMock(return_value=False)
            client.post = _post

            adapter = EmbeddingGemmaRouterAdapter(api_key="secret-deepinfra-key")
            await adapter.embed_for_classification(["x"])

        assert "Bearer secret-deepinfra-key" in captured[0]["Authorization"]
