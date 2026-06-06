"""Unit tests for MarketDataClient JWT-mint exponential backoff.

PLAN-0096 W2 T-W2-01 (deferred PLAN-0095 T-W4-02 / FIX-LIVE-GG cluster-1 item 1).

Background: when the nlp-pipeline ``PriceImpactLabellingWorker`` boots
slightly ahead of api-gateway during a fresh ``docker compose up``, the
very first JWT-mint ``POST /v1/auth/dev-login`` (or
``POST /internal/v1/service-token``) raises ``httpx.ConnectError``. Prior
to PLAN-0095 the worker swallowed the error and ran without an
``X-Internal-JWT`` header forever (article_impact_windows stayed empty
silently). The fix in ``market_data_client.py`` retries the mint up to 4
attempts with exponential backoff delays of ``(0s, 5s, 15s, 45s)``.

These tests verify the retry behaviour deterministically by stubbing
``asyncio.sleep`` so each test completes in milliseconds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from nlp_pipeline.infrastructure.http import market_data_client as mdc_module
from nlp_pipeline.infrastructure.http.market_data_client import (
    _TOKEN_MINT_RETRY_DELAYS,
    MarketDataClient,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.unit


@pytest.fixture
def _no_sleep() -> AsyncIterator[AsyncMock]:
    """Patch ``asyncio.sleep`` inside the client module so retry delays
    do not block the test suite. The real backoff is 0/5/15/45 seconds —
    65 s wall-clock per failing scenario is unacceptable in a unit test.
    """
    # Patch the symbol AS IMPORTED in the client module so the test
    # remains correct even if the module starts using a local alias.
    sleep_mock = AsyncMock()
    with patch.object(mdc_module.asyncio, "sleep", sleep_mock):
        yield sleep_mock


class TestJwtMintBackoff:
    """T-W2-01 acceptance tests for ConnectError-triggered retry."""

    @pytest.mark.asyncio
    async def test_retries_jwt_mint_on_startup_failure(
        self,
        _no_sleep: AsyncMock,
    ) -> None:
        """First 2 attempts raise ConnectError, third succeeds — no
        exception bubbles, mint returns the token from attempt 3.

        Acceptance criterion from PLAN-0096 §4 W2 T-W2-01.
        """
        # Build a mock httpx.AsyncClient whose .post() raises ConnectError
        # twice and then returns a 200 with an access_token. Using a
        # real httpx.AsyncClient + side_effect is the cleanest way to
        # simulate the cold-start race in-process.
        ok_response = httpx.Response(
            status_code=200,
            json={"access_token": "minted-after-retry"},
        )
        post_mock = AsyncMock(
            side_effect=[
                httpx.ConnectError("connection refused"),
                httpx.ConnectError("connection refused"),
                ok_response,
            ]
        )

        fake_client = AsyncMock(spec=httpx.AsyncClient)
        fake_client.post = post_mock

        mc = MarketDataClient(
            fake_client,
            "http://market-data:8003",
            api_gateway_url="http://api-gateway:8000",
        )

        token = await mc._get_internal_jwt()

        # Asserts: token returned (not None), three post() attempts made.
        assert token == "minted-after-retry"  # noqa: S105 — test fixture, not a secret
        assert post_mock.await_count == 3

        # Verify backoff delays were honoured. The first attempt fires
        # immediately (delay=0.0), then we slept twice with positive
        # delays before the third (successful) attempt. We accept any
        # non-zero positive sleep — the precise schedule is an
        # implementation detail captured by ``_TOKEN_MINT_RETRY_DELAYS``.
        non_zero_sleeps = [call.args[0] for call in _no_sleep.await_args_list if call.args and call.args[0] > 0]
        assert len(non_zero_sleeps) == 2, (
            f"Expected 2 backoff sleeps before successful attempt 3, " f"got {len(non_zero_sleeps)}: {non_zero_sleeps}"
        )
        # Sleeps must be drawn from the retry schedule (defensive — keeps
        # the test honest if someone shrinks the delay tuple).
        for s in non_zero_sleeps:
            assert s in _TOKEN_MINT_RETRY_DELAYS, f"sleep({s}) not in {_TOKEN_MINT_RETRY_DELAYS}"

    @pytest.mark.asyncio
    async def test_gives_up_after_all_attempts_fail(
        self,
        _no_sleep: AsyncMock,
    ) -> None:
        """All attempts raise ConnectError — _get_internal_jwt returns
        None (NOT an exception) so the caller can fall through to the
        legacy 401-and-warn behaviour rather than crashing the worker
        loop.

        Acceptance criterion from PLAN-0096 §4 W2 T-W2-01.
        """
        post_mock = AsyncMock(
            side_effect=[
                httpx.ConnectError("connection refused"),
            ]
            * len(_TOKEN_MINT_RETRY_DELAYS)
        )

        fake_client = AsyncMock(spec=httpx.AsyncClient)
        fake_client.post = post_mock

        mc = MarketDataClient(
            fake_client,
            "http://market-data:8003",
            api_gateway_url="http://api-gateway:8000",
        )

        # MUST NOT raise — graceful degradation contract.
        token = await mc._get_internal_jwt()

        assert token is None, "Exhausted retries must return None, not raise"
        assert post_mock.await_count == len(_TOKEN_MINT_RETRY_DELAYS)
