"""Unit tests for common.retry.retry_on_startup (PLAN-0093 Wave A-3)."""

from __future__ import annotations

import socket
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from common.retry import retry_on_startup


class TestRetryOnStartup:
    """Behaviour of the @retry_on_startup decorator."""

    @pytest.mark.asyncio
    async def test_retries_on_gaierror(self) -> None:
        """A function that raises gaierror twice then succeeds returns success.

        Regression guard for F-NPL-002: workers must survive a DNS race at
        startup (compose network not yet ready) without crashing.
        """
        call_count = {"n": 0}

        @retry_on_startup()
        async def flaky() -> str:
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise socket.gaierror("temporary DNS failure")
            return "ok"

        # Patch asyncio.sleep so the test does not actually wait 15 seconds.
        with patch("common.retry.asyncio.sleep", new=AsyncMock()):
            result = await flaky()

        assert result == "ok"
        assert call_count["n"] == 3

    @pytest.mark.asyncio
    async def test_exhausts_then_raises(self) -> None:
        """4 consecutive raises → after 3 attempts we re-raise.

        Regression guard for BP-403: the decorator must not leave background
        tasks dangling on exhaustion — it must raise cleanly so the parent
        process can exit and the compose restart-policy can take over.
        """
        call_count = {"n": 0}

        @retry_on_startup(max_attempts=3)
        async def always_fails() -> str:
            call_count["n"] += 1
            raise ConnectionRefusedError("port not open")

        with (
            patch("common.retry.asyncio.sleep", new=AsyncMock()),
            pytest.raises(ConnectionRefusedError, match="port not open"),
        ):
            await always_fails()

        # Decorator must stop at max_attempts, not keep going.
        assert call_count["n"] == 3

    @pytest.mark.asyncio
    async def test_does_not_retry_on_unexpected_exception(self) -> None:
        """ValueError (not in retry_on) propagates immediately on attempt 1.

        Regression guard for HR-031 (silent failure): a misconfiguration must
        surface immediately, not be masked as a "transient blip".
        """
        call_count = {"n": 0}

        @retry_on_startup()
        async def misconfigured() -> str:
            call_count["n"] += 1
            raise ValueError("bad config")

        with pytest.raises(ValueError, match="bad config"):
            await misconfigured()

        # Must NOT have retried — only one call.
        assert call_count["n"] == 1

    @pytest.mark.asyncio
    async def test_backoff_doubles_each_attempt(self) -> None:
        """Backoff sequence is 5s → 10s → 20s by default (mocked sleep).

        Verifies the exponential schedule advertised in the docstring so a
        future refactor that breaks the doubling is caught here.
        """
        call_count = {"n": 0}

        @retry_on_startup(max_attempts=4, backoff_seconds=5.0)
        async def always_fails() -> None:
            call_count["n"] += 1
            raise socket.gaierror("dns down")

        sleep_mock = AsyncMock()
        with (
            patch("common.retry.asyncio.sleep", new=sleep_mock),
            pytest.raises(socket.gaierror),
        ):
            await always_fails()

        # 4 attempts → 3 sleeps in between (no sleep after the final raise).
        sleep_calls = [c.args[0] for c in sleep_mock.call_args_list]
        assert sleep_calls == [5.0, 10.0, 20.0]
        assert call_count["n"] == 4


class TestRetryOnStartupArguments:
    """Decorator-arg behaviour beyond the four required cases."""

    @pytest.mark.asyncio
    async def test_custom_retry_on_tuple(self) -> None:
        """A custom retry_on tuple restricts which exceptions trigger retry."""

        @retry_on_startup(retry_on=(RuntimeError,))
        async def fn() -> None:
            raise OSError("not in retry_on now")

        # OSError no longer retryable with this custom tuple.
        with pytest.raises(OSError, match="not in retry_on now"):
            await fn()

    @pytest.mark.asyncio
    async def test_preserves_function_signature(self) -> None:
        """Wrapped function still accepts its original args + kwargs."""

        @retry_on_startup()
        async def add(a: int, b: int, *, c: int = 0) -> int:
            return a + b + c

        assert await add(1, 2, c=3) == 6

    @pytest.mark.asyncio
    async def test_preserves_function_name(self) -> None:
        """functools.wraps preserves __name__ so logs / tracebacks stay readable."""

        @retry_on_startup()
        async def my_bootstrap() -> None:
            return None

        assert my_bootstrap.__name__ == "my_bootstrap"

    @pytest.mark.asyncio
    async def test_returns_value_from_first_success(self) -> None:
        """A function that succeeds on the first attempt should not sleep."""
        sleep_mock = AsyncMock()

        @retry_on_startup()
        async def fast() -> dict[str, Any]:
            return {"status": "ok"}

        with patch("common.retry.asyncio.sleep", new=sleep_mock):
            result = await fast()

        assert result == {"status": "ok"}
        assert sleep_mock.call_count == 0

    @pytest.mark.asyncio
    async def test_asyncio_timeout_is_retried(self) -> None:
        """asyncio.TimeoutError (cold ML model on first hit) is retryable."""
        call_count = {"n": 0}

        @retry_on_startup()
        async def slow_then_fast() -> str:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise TimeoutError("upstream cold")
            return "warm"

        with patch("common.retry.asyncio.sleep", new=AsyncMock()):
            assert await slow_then_fast() == "warm"
        assert call_count["n"] == 2
