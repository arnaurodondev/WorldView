"""DeepSeekExtractionAdapter — Task #36 429 fallback to a SECONDARY model.

Context (post-outage RCA)
-------------------------
After a platform outage, a backlog saturated the PRIMARY extraction model
(Qwen/Qwen3-235B-A22B-Instruct-2507). Articles hit the consumer's
``message_processing_timeout`` and were dead-lettered. The adapter now, on a
terminal HTTP 429 (always) or a persistent timeout/5xx (when
``fallback_on_timeout``), re-issues the SAME extraction request against a
SECONDARY model (deepseek-ai/DeepSeek-V4-Flash) and returns structured metadata
(``model_used`` / ``fallback_reason`` / ``attempts``) so the usage-log audit shows
when/why the secondary served calls.

These tests patch ``adapter._client.chat.completions.create`` so the real
classification + retry + fallback loop runs, with ``asyncio.sleep`` no-op'd.
``create`` is called with ``model=<slug>`` so we assert WHICH model served by
inspecting the call kwargs.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import openai
import pytest
from ml_clients.adapters.deepseek_extraction import DeepSeekExtractionAdapter
from ml_clients.dataclasses import ExtractionInput
from ml_clients.errors import RateLimitError, RetryableError

PRIMARY = "Qwen/Qwen3-235B-A22B-Instruct-2507"
SECONDARY = "deepseek-ai/DeepSeek-V4-Flash"


def _make_adapter(**kwargs: Any) -> DeepSeekExtractionAdapter:
    # Always pin the primary so model assertions are explicit.
    kwargs.setdefault("model_id", PRIMARY)
    return DeepSeekExtractionAdapter(api_key="test-key", semaphore=asyncio.Semaphore(1), **kwargs)


def _input() -> ExtractionInput:
    return ExtractionInput(prompt="sys", context="ctx", output_schema={}, model_id="m")


def _ok_response(payload: dict[str, Any] | None = None) -> MagicMock:
    body = json.dumps(payload if payload is not None else {"relations": [{"a": 1}]})
    msg = MagicMock()
    msg.content = body
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = None
    return resp


def _rate_limit_error(retry_after: str | None = None) -> openai.RateLimitError:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    response = httpx.Response(
        status_code=429,
        headers=headers,
        request=httpx.Request("POST", "https://api.deepinfra.com/v1/openai/chat/completions"),
    )
    return openai.RateLimitError("Model busy, retry later", response=response, body=None)


def _status_error(status_code: int) -> openai.APIStatusError:
    response = httpx.Response(
        status_code=status_code,
        request=httpx.Request("POST", "https://api.deepinfra.com/v1/openai/chat/completions"),
    )
    return openai.APIStatusError(f"HTTP {status_code}", response=response, body=None)


def _timeout_error() -> openai.APITimeoutError:
    return openai.APITimeoutError(request=httpx.Request("POST", "https://api.deepinfra.com/v1/openai/chat/completions"))


def _models_called(create: AsyncMock) -> list[str]:
    """Extract the ``model=`` kwarg from every create() call, in order."""
    return [call.kwargs["model"] for call in create.await_args_list]


@pytest.fixture
def no_sleep() -> Any:
    with patch("ml_clients.adapters.deepseek_extraction.asyncio.sleep", new=AsyncMock()):
        yield


def test_model_id_property_exposes_primary_slug() -> None:
    """The adapter exposes ``model_id`` (the primary slug) for cost attribution.

    Regression guard for the LLM-cost audit (2026-07-16): the KG fallback chain
    logs ``getattr(client, "model_id", provider)`` to ``llm_usage_log``. Before
    this property existed the ``getattr`` fell through to the transport provider
    string, so every KG extraction row logged ``model_id="deepinfra"`` and
    per-model cost attribution was impossible. This asserts the real serving slug
    is now reported.
    """
    adapter = _make_adapter(model_id=PRIMARY, fallback_model_id=SECONDARY)
    assert adapter.model_id == PRIMARY
    # getattr with a default (the pattern used by fallback_chain) resolves to the
    # real slug rather than the "deepinfra" provider fallback.
    assert getattr(adapter, "model_id", "deepinfra") == PRIMARY


@pytest.mark.asyncio
async def test_success_on_primary_no_fallback(no_sleep: Any) -> None:
    """A clean primary success => model_used=primary, reason=none, no secondary call."""
    adapter = _make_adapter(fallback_model_id=SECONDARY)
    create = AsyncMock(side_effect=[_ok_response()])
    adapter._client.chat.completions.create = create  # type: ignore[method-assign]

    out = await adapter.extract(_input())

    assert out.result == {"relations": [{"a": 1}]}
    assert out.model_used == PRIMARY
    assert out.fallback_reason == "none"
    assert out.attempts == 1
    assert _models_called(create) == [PRIMARY]


@pytest.mark.asyncio
async def test_429_triggers_fallback_to_secondary(no_sleep: Any) -> None:
    """Persistent 429 on the primary => fallback to secondary; reason=rate_limit."""
    adapter = _make_adapter(fallback_model_id=SECONDARY, max_attempts=2)
    # 2 primary attempts both 429, then the secondary succeeds on its first attempt.
    create = AsyncMock(side_effect=[_rate_limit_error(), _rate_limit_error(), _ok_response()])
    adapter._client.chat.completions.create = create  # type: ignore[method-assign]

    out = await adapter.extract(_input())

    assert out.result == {"relations": [{"a": 1}]}
    assert out.model_used == SECONDARY
    assert out.fallback_reason == "rate_limit"
    # 2 primary + 1 secondary = 3 attempts reported.
    assert out.attempts == 3
    models = _models_called(create)
    assert models == [PRIMARY, PRIMARY, SECONDARY]


@pytest.mark.asyncio
async def test_timeout_triggers_fallback_when_enabled(no_sleep: Any) -> None:
    """Persistent timeout on the primary => fallback (reason=timeout) when flag on."""
    adapter = _make_adapter(fallback_model_id=SECONDARY, max_attempts=2, fallback_on_timeout=True)
    create = AsyncMock(side_effect=[_timeout_error(), _timeout_error(), _ok_response()])
    adapter._client.chat.completions.create = create  # type: ignore[method-assign]

    out = await adapter.extract(_input())

    assert out.model_used == SECONDARY
    assert out.fallback_reason == "timeout"
    assert _models_called(create)[-1] == SECONDARY


@pytest.mark.asyncio
async def test_timeout_does_not_fallback_when_disabled(no_sleep: Any) -> None:
    """With fallback_on_timeout=False a persistent timeout raises — no secondary hop."""
    adapter = _make_adapter(fallback_model_id=SECONDARY, max_attempts=2, fallback_on_timeout=False)
    create = AsyncMock(side_effect=[_timeout_error(), _timeout_error(), _ok_response()])
    adapter._client.chat.completions.create = create  # type: ignore[method-assign]

    with pytest.raises(RetryableError):
        await adapter.extract(_input())

    # Only the 2 primary attempts ran; the secondary was never called.
    assert _models_called(create) == [PRIMARY, PRIMARY]


@pytest.mark.asyncio
async def test_no_fallback_configured_raises_unchanged(no_sleep: Any) -> None:
    """Empty fallback slug => behaviour unchanged: exhaust primary retries then raise."""
    adapter = _make_adapter(fallback_model_id="", max_attempts=2)
    create = AsyncMock(side_effect=[_rate_limit_error(), _rate_limit_error()])
    adapter._client.chat.completions.create = create  # type: ignore[method-assign]

    with pytest.raises(RateLimitError):
        await adapter.extract(_input())

    assert _models_called(create) == [PRIMARY, PRIMARY]


@pytest.mark.asyncio
async def test_fallback_equal_to_primary_is_disabled(no_sleep: Any) -> None:
    """A fallback slug equal to the primary is ignored (no pointless extra hop)."""
    adapter = _make_adapter(fallback_model_id=PRIMARY, max_attempts=2)
    create = AsyncMock(side_effect=[_rate_limit_error(), _rate_limit_error()])
    adapter._client.chat.completions.create = create  # type: ignore[method-assign]

    with pytest.raises(RateLimitError):
        await adapter.extract(_input())

    assert _models_called(create) == [PRIMARY, PRIMARY]


@pytest.mark.asyncio
async def test_fallback_also_fails_raises_primary_error(no_sleep: Any) -> None:
    """When the secondary ALSO fails, the primary's 429 is re-raised (never empty)."""
    adapter = _make_adapter(fallback_model_id=SECONDARY, max_attempts=1)
    # 1 primary 429, then 1 secondary 5xx (also transient) — both exhausted.
    create = AsyncMock(side_effect=[_rate_limit_error(), _status_error(503)])
    adapter._client.chat.completions.create = create  # type: ignore[method-assign]

    with pytest.raises(RateLimitError):
        await adapter.extract(_input())

    assert _models_called(create) == [PRIMARY, SECONDARY]


@pytest.mark.asyncio
async def test_server_error_reason_on_fallback(no_sleep: Any) -> None:
    """A persistent 5xx on the primary tags reason=server_error on the fallback."""
    adapter = _make_adapter(fallback_model_id=SECONDARY, max_attempts=1, fallback_on_timeout=True)
    create = AsyncMock(side_effect=[_status_error(500), _ok_response()])
    adapter._client.chat.completions.create = create  # type: ignore[method-assign]

    out = await adapter.extract(_input())

    assert out.model_used == SECONDARY
    assert out.fallback_reason == "server_error"
