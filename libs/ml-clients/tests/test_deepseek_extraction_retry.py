"""DeepSeekExtractionAdapter — bounded in-adapter retry on transient failures.

Context (2026-06-14 extraction transient-failure resilience)
------------------------------------------------------------
The dominant live failure for deep relation-extraction is HTTP 429
``engine_overloaded`` ("Model busy, retry later") from DeepInfra under throughput
bursts.  Before the fix the adapter made ONE shot and a single 429/timeout raised
``RetryableError`` immediately, which the consumer's OFF retry path then committed
as an empty ``relations`` (silent-null).  These tests assert the adapter now:

  * retries 429 / 5xx / timeout / connection errors and succeeds on a later attempt,
  * does NOT retry 4xx (a retry cannot fix bad input),
  * honours the ``Retry-After`` header on 429s,
  * raises (never returns empty) once retries are exhausted,
  * bounds backoff/jitter and the total per-call wall-time budget.

We patch ``adapter._client.chat.completions.create`` directly so the real
classification + retry loop runs; ``asyncio.sleep`` is patched to a no-op so the
tests do not actually wait out the backoff.
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
from ml_clients.errors import FatalError, RateLimitError, RetryableError


def _make_adapter(**kwargs: Any) -> DeepSeekExtractionAdapter:
    return DeepSeekExtractionAdapter(
        api_key="test-key",
        semaphore=asyncio.Semaphore(1),
        **kwargs,
    )


def _input() -> ExtractionInput:
    return ExtractionInput(prompt="sys", context="ctx", output_schema={}, model_id="m")


def _ok_response(payload: dict[str, Any] | None = None) -> MagicMock:
    """Build a minimal openai-shaped successful chat-completion response."""
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


@pytest.fixture
def no_sleep() -> Any:
    """Patch the adapter's asyncio.sleep so backoff does not actually block."""
    with patch("ml_clients.adapters.deepseek_extraction.asyncio.sleep", new=AsyncMock()) as mock_sleep:
        yield mock_sleep


@pytest.mark.asyncio
async def test_retry_on_429_then_success(no_sleep: AsyncMock) -> None:
    """A 429 on the first attempt is retried and the second attempt succeeds."""
    adapter = _make_adapter()
    create = AsyncMock(side_effect=[_rate_limit_error(), _ok_response()])
    adapter._client.chat.completions.create = create  # type: ignore[method-assign]

    out = await adapter.extract(_input())

    assert out.result == {"relations": [{"a": 1}]}
    assert create.await_count == 2
    assert no_sleep.await_count == 1  # exactly one backoff between the two attempts


@pytest.mark.asyncio
async def test_retry_on_5xx_then_success(no_sleep: AsyncMock) -> None:
    """A provider 5xx is transient and retried."""
    adapter = _make_adapter()
    create = AsyncMock(side_effect=[_status_error(503), _ok_response()])
    adapter._client.chat.completions.create = create  # type: ignore[method-assign]

    out = await adapter.extract(_input())

    assert out.result == {"relations": [{"a": 1}]}
    assert create.await_count == 2


@pytest.mark.asyncio
async def test_retry_on_timeout_then_success(no_sleep: AsyncMock) -> None:
    """An openai APITimeoutError is transient and retried."""
    adapter = _make_adapter()
    create = AsyncMock(side_effect=[_timeout_error(), _ok_response()])
    adapter._client.chat.completions.create = create  # type: ignore[method-assign]

    out = await adapter.extract(_input())

    assert out.result == {"relations": [{"a": 1}]}
    assert create.await_count == 2


@pytest.mark.asyncio
async def test_retry_on_wall_clock_timeout_then_success(no_sleep: AsyncMock) -> None:
    """The per-attempt asyncio.wait_for TimeoutError is transient and retried."""
    adapter = _make_adapter()
    create = AsyncMock(side_effect=[TimeoutError("wall clock"), _ok_response()])
    adapter._client.chat.completions.create = create  # type: ignore[method-assign]

    out = await adapter.extract(_input())

    assert out.result == {"relations": [{"a": 1}]}
    assert create.await_count == 2


@pytest.mark.asyncio
async def test_no_retry_on_4xx(no_sleep: AsyncMock) -> None:
    """A 4xx is fatal — raised immediately with NO retry."""
    adapter = _make_adapter()
    create = AsyncMock(side_effect=[_status_error(422), _ok_response()])
    adapter._client.chat.completions.create = create  # type: ignore[method-assign]

    with pytest.raises(FatalError):
        await adapter.extract(_input())

    assert create.await_count == 1  # NOT retried
    assert no_sleep.await_count == 0


@pytest.mark.asyncio
async def test_exhausted_retries_raises_not_empty(no_sleep: AsyncMock) -> None:
    """Persistent 429 across all attempts raises RetryableError, never empty result."""
    # Pin max_attempts=3 explicitly to exercise the MULTI-retry exhaustion path
    # (the default was lowered 3 -> 2 in Task #5; this test asserts the retry-loop
    # behaviour, not the default attempt count).
    adapter = _make_adapter(max_attempts=3)
    create = AsyncMock(side_effect=[_rate_limit_error(), _rate_limit_error(), _rate_limit_error()])
    adapter._client.chat.completions.create = create  # type: ignore[method-assign]

    with pytest.raises(RetryableError):
        await adapter.extract(_input())

    assert create.await_count == 3  # 1 initial + 2 retries
    assert no_sleep.await_count == 2  # backoff between the three attempts


@pytest.mark.asyncio
async def test_retry_after_header_honoured(no_sleep: AsyncMock) -> None:
    """A numeric Retry-After header drives the backoff sleep duration."""
    adapter = _make_adapter(backoff_cap_s=30.0)
    create = AsyncMock(side_effect=[_rate_limit_error(retry_after="7"), _ok_response()])
    adapter._client.chat.completions.create = create  # type: ignore[method-assign]

    await adapter.extract(_input())

    # The single backoff sleep used the Retry-After value (7s), not random jitter.
    no_sleep.assert_awaited_once_with(7.0)


@pytest.mark.asyncio
async def test_retry_after_capped_at_backoff_cap(no_sleep: AsyncMock) -> None:
    """A hostile/large Retry-After is capped at backoff_cap_s so it cannot blow the budget."""
    adapter = _make_adapter(backoff_cap_s=5.0)
    create = AsyncMock(side_effect=[_rate_limit_error(retry_after="9999"), _ok_response()])
    adapter._client.chat.completions.create = create  # type: ignore[method-assign]

    await adapter.extract(_input())

    no_sleep.assert_awaited_once_with(5.0)


@pytest.mark.asyncio
async def test_backoff_bounded_by_cap_with_jitter(no_sleep: AsyncMock) -> None:
    """Without Retry-After, the backoff is full-jitter within [0, cap]."""
    # max_attempts=3 so the two 5xx errors are both retried (default is 2 since
    # Task #5); this test asserts backoff bounds across MULTIPLE retries.
    adapter = _make_adapter(max_attempts=3, backoff_base_s=2.0, backoff_cap_s=20.0)
    create = AsyncMock(side_effect=[_status_error(500), _status_error(500), _ok_response()])
    adapter._client.chat.completions.create = create  # type: ignore[method-assign]

    await adapter.extract(_input())

    assert no_sleep.await_count == 2
    for call in no_sleep.await_args_list:
        backoff = call.args[0]
        assert 0.0 <= backoff <= 20.0


@pytest.mark.asyncio
async def test_total_budget_stops_retry_early(no_sleep: AsyncMock) -> None:
    """When the next attempt + backoff would exceed the total budget, stop retrying.

    With a tiny total budget (1s) the first 429 cannot fit another 300s attempt, so
    the loop breaks after one attempt and re-raises the transient error rather than
    sleeping/retrying.
    """
    adapter = _make_adapter(total_budget_s=1.0)  # per-attempt default 300s > budget
    create = AsyncMock(side_effect=[_rate_limit_error(), _ok_response()])
    adapter._client.chat.completions.create = create  # type: ignore[method-assign]

    with pytest.raises(RateLimitError):
        await adapter.extract(_input())

    assert create.await_count == 1  # no second attempt fits the budget
    assert no_sleep.await_count == 0


@pytest.mark.asyncio
async def test_max_attempts_one_makes_single_call(no_sleep: AsyncMock) -> None:
    """max_attempts=1 disables retry: a single 429 raises after one call."""
    adapter = _make_adapter(max_attempts=1)
    create = AsyncMock(side_effect=[_rate_limit_error(), _ok_response()])
    adapter._client.chat.completions.create = create  # type: ignore[method-assign]

    with pytest.raises(RetryableError):
        await adapter.extract(_input())

    assert create.await_count == 1
    assert no_sleep.await_count == 0
