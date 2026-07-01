"""Unit tests for intelligence HTTP clients.

PLAN-0089 Wave L-5b (T-WL5B-06).

Covers:
  - BP-235: each client must set an explicit httpx.Timeout on its AsyncClient
  - Retry budget: 5xx → retry once → second failure → return None
  - Internal JWT header present in every request
  - Successful JSON parse into typed response models
  - Graceful None on 404 and malformed JSON
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest
from market_data.infrastructure.clients.intelligence_clients import (
    S6NewsRollup,
    S6NewsRollupClient,
    S7IntelligenceClient,
    S7IntelligenceRollup,
    S8BriefClient,
    S8BriefFlag,
    S10AlertClient,
    S10AlertFlag,
    _BaseIntelligenceClient,
)

pytestmark = pytest.mark.unit


# ── BP-235: explicit timeout guard ────────────────────────────────────────────


class TestExplicitTimeout:
    """BP-235: httpx.AsyncClient must always be constructed with an explicit Timeout."""

    @pytest.mark.asyncio
    async def test_base_client_sets_explicit_timeout(self) -> None:
        """_BaseIntelligenceClient must set timeout=httpx.Timeout(N) on the client."""
        # Inspect the client constructed by instantiating a concrete subclass.
        client = S6NewsRollupClient("http://example.com")
        # The internal httpx client must have a non-default timeout.
        # httpx.Timeout default is 5s; we require an explicit override.
        assert client._client.timeout == httpx.Timeout(_BaseIntelligenceClient._TIMEOUT_SECONDS)
        # Cleanup via async close (avoids DeprecationWarning from get_event_loop)
        await client.aclose()

    def test_s6_client_timeout(self) -> None:
        client = S6NewsRollupClient("http://s6:8006")
        assert isinstance(client._client.timeout, httpx.Timeout)
        assert client._client.timeout.connect == _BaseIntelligenceClient._TIMEOUT_SECONDS

    def test_s7_client_timeout(self) -> None:
        client = S7IntelligenceClient("http://s7:8007")
        assert isinstance(client._client.timeout, httpx.Timeout)

    def test_s10_client_timeout(self) -> None:
        client = S10AlertClient("http://s10:8010")
        assert isinstance(client._client.timeout, httpx.Timeout)

    def test_s8_client_timeout(self) -> None:
        client = S8BriefClient("http://s8:8008")
        assert isinstance(client._client.timeout, httpx.Timeout)


# ── Internal JWT header present ───────────────────────────────────────────────


class TestInternalJwtHeader:
    """Every HTTP request must include X-Internal-JWT."""

    @pytest.mark.asyncio
    async def test_s6_sends_internal_jwt_header(self) -> None:
        """S6 client passes X-Internal-JWT on the GET request."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "news_count_7d": 3,
            "llm_relevance_7d_max": 0.8,
            "display_relevance_7d_weighted": 0.7,
        }

        captured_headers: list[dict] = []

        async def _mock_get(url: str, headers: dict | None = None, **kwargs: object) -> httpx.Response:
            captured_headers.append(headers or {})
            return mock_response

        client = S6NewsRollupClient("http://s6:8006")
        client._client.get = _mock_get  # type: ignore[method-assign]

        result = await client.get_news_rollup("inst-001")

        assert result is not None
        assert len(captured_headers) == 1
        assert "X-Internal-JWT" in captured_headers[0]

    @pytest.mark.asyncio
    async def test_s7_sends_internal_jwt_header(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"recent_contradiction_count": 1}

        captured_headers: list[dict] = []

        async def _mock_get(url: str, headers: dict | None = None, **kwargs: object) -> httpx.Response:
            captured_headers.append(headers or {})
            return mock_response

        client = S7IntelligenceClient("http://s7:8007")
        client._client.get = _mock_get  # type: ignore[method-assign]

        await client.get_intelligence_rollup("inst-001")
        assert "X-Internal-JWT" in captured_headers[0]

    @pytest.mark.asyncio
    async def test_s10_sends_internal_jwt_header(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"has_active_alert": True}

        captured_headers: list[dict] = []

        async def _mock_get(url: str, headers: dict | None = None, **kwargs: object) -> httpx.Response:
            captured_headers.append(headers or {})
            return mock_response

        client = S10AlertClient("http://s10:8010")
        client._client.get = _mock_get  # type: ignore[method-assign]

        await client.get_active_alert_flag("inst-001")
        assert "X-Internal-JWT" in captured_headers[0]

    @pytest.mark.asyncio
    async def test_s8_sends_internal_jwt_header(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"has_ai_brief": False}

        captured_headers: list[dict] = []

        async def _mock_get(url: str, headers: dict | None = None, **kwargs: object) -> httpx.Response:
            captured_headers.append(headers or {})
            return mock_response

        client = S8BriefClient("http://s8:8008")
        client._client.get = _mock_get  # type: ignore[method-assign]

        await client.get_ai_brief_flag("inst-001")
        assert "X-Internal-JWT" in captured_headers[0]


# ── Retry budget ──────────────────────────────────────────────────────────────


class TestRetryBudget:
    """5xx → retry once → second failure → return None."""

    @pytest.mark.asyncio
    async def test_5xx_retries_once_then_returns_none(self) -> None:
        """Two consecutive 5xx responses → None (retry budget exhausted)."""
        call_count = [0]

        async def _mock_get(url: str, headers: dict | None = None, **kwargs: object) -> httpx.Response:
            call_count[0] += 1
            mock_resp = MagicMock(spec=httpx.Response)
            mock_resp.status_code = 503
            return mock_resp

        client = S6NewsRollupClient("http://s6:8006")
        client._client.get = _mock_get  # type: ignore[method-assign]

        result = await client.get_news_rollup("inst-001")

        assert result is None
        # Must have retried exactly once (2 attempts total)
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_5xx_then_success_returns_data(self) -> None:
        """First 5xx → retry → second 200 → return data."""
        call_count = [0]

        async def _mock_get(url: str, headers: dict | None = None, **kwargs: object) -> httpx.Response:
            call_count[0] += 1
            mock_resp = MagicMock(spec=httpx.Response)
            if call_count[0] == 1:
                mock_resp.status_code = 503
            else:
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "news_count_7d": 7,
                    "llm_relevance_7d_max": 0.9,
                    "display_relevance_7d_weighted": 0.85,
                }
            return mock_resp

        client = S6NewsRollupClient("http://s6:8006")
        client._client.get = _mock_get  # type: ignore[method-assign]

        result = await client.get_news_rollup("inst-001")

        assert result is not None
        assert result.news_count_7d == 7
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_timeout_retries_once_then_returns_none(self) -> None:
        """Timeout → retry → second timeout → None."""
        call_count = [0]

        async def _mock_get(url: str, headers: dict | None = None, **kwargs: object) -> None:
            call_count[0] += 1
            raise httpx.ReadTimeout("timed out", request=None)  # type: ignore[arg-type]

        client = S7IntelligenceClient("http://s7:8007")
        client._client.get = _mock_get  # type: ignore[method-assign]

        result = await client.get_intelligence_rollup("inst-001")

        assert result is None
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_404_returns_none_without_retry(self) -> None:
        """404 is a 4xx (caller error) — no retry, return None."""
        call_count = [0]

        async def _mock_get(url: str, headers: dict | None = None, **kwargs: object) -> httpx.Response:
            call_count[0] += 1
            mock_resp = MagicMock(spec=httpx.Response)
            mock_resp.status_code = 404
            return mock_resp

        client = S10AlertClient("http://s10:8010")
        client._client.get = _mock_get  # type: ignore[method-assign]

        result = await client.get_active_alert_flag("inst-001")

        assert result is None
        # 404 must not trigger retry
        assert call_count[0] == 1


# ── Internal-JWT auth-failure guardrail (2026-07-01 audit) ────────────────────


class TestAuthFailureGuardrail:
    """A 401/403 on an internal call must be logged loudly (never silently swallowed).

    Regression guard for the silent-401 class of bug: previously a 401 was
    returned as a plain 4xx with NO log and the caller degraded to None, so a
    misconfigured internal-JWT key looked identical to "no data". The client
    must now emit an ERROR-level ``intelligence_client_auth_failure`` log.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [401, 403])
    async def test_401_403_logged_at_error_and_not_retried(self, status: int, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = [0]

        async def _mock_get(url: str, headers: dict | None = None, **kwargs: object) -> httpx.Response:
            call_count[0] += 1
            mock_resp = MagicMock(spec=httpx.Response)
            mock_resp.status_code = status
            return mock_resp

        # Capture ERROR-level log events emitted by the client module logger.
        error_events: list[tuple[str, dict]] = []

        def _capture_error(event: str, **kwargs: object) -> None:
            error_events.append((event, dict(kwargs)))

        import market_data.infrastructure.clients.intelligence_clients as mod

        monkeypatch.setattr(mod.logger, "error", _capture_error)

        client = S6NewsRollupClient("http://s6:8006")
        client._client.get = _mock_get  # type: ignore[method-assign]

        result = await client.get_news_rollup("inst-001")

        # Caller still degrades gracefully to None (keep-last-known semantics)...
        assert result is None
        # ...but the auth failure is NOT retried (4xx) and IS logged at ERROR.
        assert call_count[0] == 1
        assert any(
            evt == "intelligence_client_auth_failure" and kw.get("auth_failure") is True for evt, kw in error_events
        ), f"expected loud auth-failure ERROR log, got: {error_events}"

    @pytest.mark.asyncio
    async def test_404_does_not_emit_auth_failure_log(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A plain 404 (not an auth failure) must NOT trigger the auth-failure ERROR log."""

        async def _mock_get(url: str, headers: dict | None = None, **kwargs: object) -> httpx.Response:
            mock_resp = MagicMock(spec=httpx.Response)
            mock_resp.status_code = 404
            return mock_resp

        error_events: list[str] = []

        import market_data.infrastructure.clients.intelligence_clients as mod

        monkeypatch.setattr(mod.logger, "error", lambda event, **kw: error_events.append(event))

        client = S7IntelligenceClient("http://s7:8007")
        client._client.get = _mock_get  # type: ignore[method-assign]

        result = await client.get_intelligence_rollup("inst-001")

        assert result is None
        assert "intelligence_client_auth_failure" not in error_events


# ── Successful parse ──────────────────────────────────────────────────────────


class TestSuccessfulParse:
    """Validate that each client correctly parses the upstream JSON body."""

    @pytest.mark.asyncio
    async def test_s6_parses_all_three_fields(self) -> None:
        async def _mock_get(url: str, headers: dict | None = None, **kwargs: object) -> MagicMock:
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {
                "news_count_7d": 12,
                "llm_relevance_7d_max": 0.91,
                "display_relevance_7d_weighted": 0.76,
            }
            return resp

        client = S6NewsRollupClient("http://s6:8006")
        client._client.get = _mock_get  # type: ignore[method-assign]
        result = await client.get_news_rollup("inst-999")

        assert isinstance(result, S6NewsRollup)
        assert result.news_count_7d == 12
        assert result.llm_relevance_7d_max == pytest.approx(0.91)
        assert result.display_relevance_7d_weighted == pytest.approx(0.76)

    @pytest.mark.asyncio
    async def test_s7_parses_contradiction_count(self) -> None:
        async def _mock_get(url: str, headers: dict | None = None, **kwargs: object) -> MagicMock:
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"recent_contradiction_count": 5}
            return resp

        client = S7IntelligenceClient("http://s7:8007")
        client._client.get = _mock_get  # type: ignore[method-assign]
        result = await client.get_intelligence_rollup("inst-999")

        assert isinstance(result, S7IntelligenceRollup)
        assert result.recent_contradiction_count == 5

    @pytest.mark.asyncio
    async def test_s10_parses_alert_flag(self) -> None:
        async def _mock_get(url: str, headers: dict | None = None, **kwargs: object) -> MagicMock:
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"has_active_alert": True}
            return resp

        client = S10AlertClient("http://s10:8010")
        client._client.get = _mock_get  # type: ignore[method-assign]
        result = await client.get_active_alert_flag("inst-999")

        assert isinstance(result, S10AlertFlag)
        assert result.has_active_alert is True

    @pytest.mark.asyncio
    async def test_s8_parses_brief_flag(self) -> None:
        async def _mock_get(url: str, headers: dict | None = None, **kwargs: object) -> MagicMock:
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"has_ai_brief": False}
            return resp

        client = S8BriefClient("http://s8:8008")
        client._client.get = _mock_get  # type: ignore[method-assign]
        result = await client.get_ai_brief_flag("inst-999")

        assert isinstance(result, S8BriefFlag)
        assert result.has_ai_brief is False

    @pytest.mark.asyncio
    async def test_s6_returns_none_on_malformed_json(self) -> None:
        """Malformed JSON payload from S6 → None (no crash)."""

        async def _mock_get(url: str, headers: dict | None = None, **kwargs: object) -> MagicMock:
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.side_effect = ValueError("not json")
            return resp

        client = S6NewsRollupClient("http://s6:8006")
        client._client.get = _mock_get  # type: ignore[method-assign]
        result = await client.get_news_rollup("inst-999")

        assert result is None
