"""Unit tests for EmailScheduler, S8BriefingClient, and S3MarketDataClient."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import httpx
import pytest
from alert.config import Settings
from alert.domain.email_provider import EmailProviderError
from alert.domain.entities import EmailPreference
from alert.infrastructure.clients.s3_client import S3MarketDataClient
from alert.infrastructure.clients.s8_client import BriefingClientError, S8BriefingClient
from alert.infrastructure.email.scheduler import EmailScheduler
from alert.infrastructure.email.template import render_digest_email

# ── Helpers ───────────────────────────────────────────────────────────────────

_USER_ID = UUID("01912345-6789-7abc-8def-0123456789ab")
_TENANT_ID = UUID("01912345-6789-7abc-8def-0123456789ac")


def _settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "email_provider": "resend",
        "email_from_address": "noreply@example.com",
        "s8_base_url": "http://s8:8008",
        "s8_internal_token": "s8-token",
        "s1_internal_token": "s1-token",
        "s3_market_data_base_url": "http://s3:8003",
        "s1_portfolio_base_url": "http://s1:8001",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _pref(email_address: str | None = "user@example.com") -> EmailPreference:
    return EmailPreference(
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        email_address=email_address,
        weekly_digest_enabled=True,
        send_day_of_week=0,
        send_hour_utc=8,
    )


def _make_session_factory(prefs: list[EmailPreference] | None = None) -> MagicMock:
    """Build a mock session factory that returns a context-manager-compatible session."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    session.add = MagicMock()

    # Patch EmailPreferenceRepository inside the session context
    if prefs is not None:
        mock_repo = AsyncMock()
        mock_repo.list_scheduled_users = AsyncMock(return_value=prefs)
        with patch(
            "alert.infrastructure.email.scheduler.EmailPreferenceRepository",
            return_value=mock_repo,
        ):
            pass  # repo will be patched separately in each test

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


def _make_scheduler(
    *,
    prefs: list[EmailPreference] | None = None,
    email_provider: Any = None,
    s1_client: Any = None,
    s3_client: Any = None,
    s8_client: Any = None,
    settings: Settings | None = None,
) -> tuple[EmailScheduler, MagicMock, Any]:
    sf = _make_session_factory(prefs)
    if email_provider is None:
        ep = AsyncMock()
        ep.send = AsyncMock(return_value="msg-001")
    else:
        ep = email_provider
    s1 = s1_client or AsyncMock()
    s3 = s3_client or AsyncMock()
    s3.get_ohlcv_bulk = AsyncMock(return_value=[])
    s3.get_fundamentals = AsyncMock(return_value=[])
    s8 = s8_client or AsyncMock()
    s8.request_briefing = AsyncMock(return_value={"narrative": "Test narrative"})
    sched = EmailScheduler(
        session_factory=sf,
        email_provider=ep,
        settings=settings or _settings(),
        s1_client=s1,
        s3_client=s3,
        s8_client=s8,
    )
    return sched, sf, ep


# ── S8BriefingClient ──────────────────────────────────────────────────────────


class TestS8BriefingClient:
    @pytest.mark.unit
    async def test_request_briefing_success(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"narrative": "Risk summary here", "citations": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        client = S8BriefingClient(_settings(), client=mock_client)
        result = await client.request_briefing(
            user_id=_USER_ID,
            tenant_id=_TENANT_ID,
            portfolio_context={"holdings": []},
            market_snapshots=[],
        )

        assert result["narrative"] == "Risk summary here"
        mock_client.post.assert_called_once()

    @pytest.mark.unit
    async def test_request_briefing_sends_internal_token(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"narrative": "x"}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        client = S8BriefingClient(_settings(s8_internal_token="secret-s8"), client=mock_client)
        await client.request_briefing(_USER_ID, _TENANT_ID, {}, [])

        headers = mock_client.post.call_args.kwargs["headers"]
        assert headers["X-Internal-Token"] == "secret-s8"

    @pytest.mark.unit
    async def test_request_briefing_401_raises_briefing_client_error(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("401", request=MagicMock(), response=mock_resp)
        mock_client.post = AsyncMock(return_value=mock_resp)

        client = S8BriefingClient(_settings(), client=mock_client)
        with pytest.raises(BriefingClientError, match="401"):
            await client.request_briefing(_USER_ID, _TENANT_ID, {}, [])

    @pytest.mark.unit
    async def test_request_briefing_503_raises_briefing_client_error(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.text = "Service Unavailable"
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("503", request=MagicMock(), response=mock_resp)
        mock_client.post = AsyncMock(return_value=mock_resp)

        client = S8BriefingClient(_settings(), client=mock_client)
        with pytest.raises(BriefingClientError, match="503"):
            await client.request_briefing(_USER_ID, _TENANT_ID, {}, [])

    @pytest.mark.unit
    async def test_request_briefing_transport_error_raises(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

        client = S8BriefingClient(_settings(), client=mock_client)
        with pytest.raises(BriefingClientError, match="transport"):
            await client.request_briefing(_USER_ID, _TENANT_ID, {}, [])


# ── S3MarketDataClient ────────────────────────────────────────────────────────


class TestS3MarketDataClient:
    @pytest.mark.unit
    async def test_get_ohlcv_bulk_success_list_response(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"entity_id": str(_USER_ID), "close": 150.0}]
        mock_resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        client = S3MarketDataClient(_settings(), client=mock_client)
        result = await client.get_ohlcv_bulk([_USER_ID], days=7)

        assert len(result) == 1
        assert result[0]["close"] == 150.0

    @pytest.mark.unit
    async def test_get_ohlcv_bulk_results_key_response(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [{"entity_id": str(_USER_ID)}]}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        client = S3MarketDataClient(_settings(), client=mock_client)
        result = await client.get_ohlcv_bulk([_USER_ID])

        assert len(result) == 1

    @pytest.mark.unit
    async def test_get_ohlcv_bulk_empty_entity_ids_returns_empty(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        client = S3MarketDataClient(_settings(), client=mock_client)
        result = await client.get_ohlcv_bulk([])
        assert result == []
        mock_client.get.assert_not_called()

    @pytest.mark.unit
    async def test_get_ohlcv_bulk_503_returns_empty(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("503", request=MagicMock(), response=MagicMock())
        mock_client.get = AsyncMock(return_value=mock_resp)

        client = S3MarketDataClient(_settings(), client=mock_client)
        result = await client.get_ohlcv_bulk([_USER_ID])
        assert result == []

    @pytest.mark.unit
    async def test_get_fundamentals_success(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"pe_ratio": 25.0}]
        mock_resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        client = S3MarketDataClient(_settings(), client=mock_client)
        result = await client.get_fundamentals([_USER_ID])
        assert result[0]["pe_ratio"] == 25.0

    @pytest.mark.unit
    async def test_get_fundamentals_transport_error_returns_empty(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        client = S3MarketDataClient(_settings(), client=mock_client)
        result = await client.get_fundamentals([_USER_ID])
        assert result == []


# ── EmailScheduler ────────────────────────────────────────────────────────────


class TestEmailScheduler:
    @pytest.mark.unit
    async def test_run_processes_scheduled_users(self) -> None:
        """run() queries list_scheduled_users and processes each user."""
        pref = _pref()
        sched, _sf, ep = _make_scheduler()

        with patch("alert.infrastructure.email.scheduler.EmailPreferenceRepository") as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.list_scheduled_users = AsyncMock(return_value=[pref])
            mock_repo_cls.return_value = mock_repo

            with patch.object(sched, "_fetch_user_email_direct", AsyncMock(return_value="u@e.com")):
                await sched.run()

        ep.send.assert_called_once()

    @pytest.mark.unit
    async def test_run_skips_user_when_no_email_and_s1_unavailable(self) -> None:
        """If email_address is null and S1 returns None, user is skipped."""
        pref = _pref(email_address=None)
        sched, _sf, ep = _make_scheduler()

        with patch("alert.infrastructure.email.scheduler.EmailPreferenceRepository") as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.list_scheduled_users = AsyncMock(return_value=[pref])
            mock_repo_cls.return_value = mock_repo

            with patch.object(sched, "_fetch_user_email_direct", AsyncMock(return_value=None)):
                await sched.run()

        ep.send.assert_not_called()

    @pytest.mark.unit
    async def test_s8_unavailable_sends_partial_email(self) -> None:
        """BriefingClientError from S8 → partial email still sent."""
        pref = _pref()
        s8 = AsyncMock()
        s8.request_briefing = AsyncMock(side_effect=BriefingClientError("S8 down"))
        sched, _sf, ep = _make_scheduler(s8_client=s8)

        with patch("alert.infrastructure.email.scheduler.EmailPreferenceRepository") as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.list_scheduled_users = AsyncMock(return_value=[pref])
            mock_repo_cls.return_value = mock_repo

            await sched.run()

        # Email was sent even without narrative
        ep.send.assert_called_once()

    @pytest.mark.unit
    async def test_retry_succeeds_on_second_attempt(self) -> None:
        """First send fails, second attempt succeeds."""
        pref = _pref()
        ep = AsyncMock()
        ep.send = AsyncMock(side_effect=[EmailProviderError("timeout"), "msg-001"])
        sched, _sf, _ = _make_scheduler(email_provider=ep)

        with (
            patch("alert.infrastructure.email.scheduler.EmailPreferenceRepository") as mock_repo_cls,
            patch(
                "alert.infrastructure.email.scheduler.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            mock_repo = AsyncMock()
            mock_repo.list_scheduled_users = AsyncMock(return_value=[pref])
            mock_repo_cls.return_value = mock_repo

            await sched.run()

        assert ep.send.call_count == 2

    @pytest.mark.unit
    async def test_all_retries_exhausted_logs_failed(self) -> None:
        """All 4 send attempts fail → email_log.status = 'failed'."""
        pref = _pref()
        ep = AsyncMock()
        ep.send = AsyncMock(side_effect=EmailProviderError("refused"))
        sched, _sf, _ = _make_scheduler(email_provider=ep)

        log_rows: list[Any] = []

        def _capture_add(row: Any) -> None:  # sync — MagicMock.add is sync
            log_rows.append(row)

        with (
            patch("alert.infrastructure.email.scheduler.EmailPreferenceRepository") as mock_repo_cls,
            patch(
                "alert.infrastructure.email.scheduler.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            mock_repo = AsyncMock()
            mock_repo.list_scheduled_users = AsyncMock(return_value=[pref])
            mock_repo_cls.return_value = mock_repo

            # Capture session.add calls to inspect the log row
            session_mock = _sf.return_value.__aenter__.return_value
            session_mock.add = MagicMock(side_effect=_capture_add)

            await sched.run()

        # 4 total send attempts (initial + 3 retries)
        assert ep.send.call_count == 4
        # At least one EmailLogModel was logged with status=failed
        failed_rows = [r for r in log_rows if hasattr(r, "status") and r.status == "failed"]
        assert len(failed_rows) >= 1

    @pytest.mark.unit
    async def test_retry_backoff_delays_are_applied(self) -> None:
        """asyncio.sleep is called with increasing delays on retry."""
        pref = _pref()
        ep = AsyncMock()
        ep.send = AsyncMock(
            side_effect=[
                EmailProviderError("fail 1"),
                EmailProviderError("fail 2"),
                "msg-003",  # succeeds on 3rd
            ]
        )
        sched, _sf, _ = _make_scheduler(email_provider=ep)

        with (
            patch("alert.infrastructure.email.scheduler.EmailPreferenceRepository") as mock_repo_cls,
            patch(
                "alert.infrastructure.email.scheduler.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep,
        ):
            mock_repo = AsyncMock()
            mock_repo.list_scheduled_users = AsyncMock(return_value=[pref])
            mock_repo_cls.return_value = mock_repo

            await sched.run()

        # Two delays before the successful 3rd attempt: 1.0s and 2.0s
        sleep_delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert sleep_delays == [1.0, 2.0]

    @pytest.mark.unit
    async def test_email_log_inserted_on_success(self) -> None:
        """On successful send, an EmailLogModel row is inserted with status='sent'."""
        pref = _pref()
        sched, _sf, _ep = _make_scheduler()

        log_rows: list[Any] = []

        with patch("alert.infrastructure.email.scheduler.EmailPreferenceRepository") as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.list_scheduled_users = AsyncMock(return_value=[pref])
            mock_repo_cls.return_value = mock_repo

            session_mock = _sf.return_value.__aenter__.return_value
            session_mock.add = MagicMock(side_effect=lambda row: log_rows.append(row))

            await sched.run()

        sent_rows = [r for r in log_rows if hasattr(r, "status") and r.status == "sent"]
        assert len(sent_rows) >= 1

    @pytest.mark.unit
    async def test_run_no_users_no_sends(self) -> None:
        """If no users are scheduled, no sends occur."""
        sched, _sf, ep = _make_scheduler()

        with patch("alert.infrastructure.email.scheduler.EmailPreferenceRepository") as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.list_scheduled_users = AsyncMock(return_value=[])
            mock_repo_cls.return_value = mock_repo

            await sched.run()

        ep.send.assert_not_called()

    @pytest.mark.unit
    async def test_uses_email_address_from_preferences(self) -> None:
        """If email_address is set in preferences, S1 is not called."""
        pref = _pref(email_address="override@example.com")
        sched, _sf, ep = _make_scheduler()

        with (
            patch("alert.infrastructure.email.scheduler.EmailPreferenceRepository") as mock_repo_cls,
            patch.object(sched, "_fetch_user_email_direct", AsyncMock()) as mock_s1,
        ):
            mock_repo = AsyncMock()
            mock_repo.list_scheduled_users = AsyncMock(return_value=[pref])
            mock_repo_cls.return_value = mock_repo

            await sched.run()

        mock_s1.assert_not_called()
        ep.send.assert_called_once()
        call_kwargs = ep.send.call_args.kwargs
        assert call_kwargs["to"] == "override@example.com"

    @pytest.mark.unit
    async def test_skipped_email_log_inserted(self) -> None:
        """Skipped users (no address) have a 'skipped' log row inserted."""
        pref = _pref(email_address=None)
        sched, sf, _ep = _make_scheduler()

        log_rows: list[Any] = []

        with patch("alert.infrastructure.email.scheduler.EmailPreferenceRepository") as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.list_scheduled_users = AsyncMock(return_value=[pref])
            mock_repo_cls.return_value = mock_repo

            with patch.object(sched, "_fetch_user_email_direct", AsyncMock(return_value=None)):
                session_mock = sf.return_value.__aenter__.return_value
                session_mock.add = MagicMock(side_effect=lambda row: log_rows.append(row))
                await sched.run()

        skipped = [r for r in log_rows if hasattr(r, "status") and r.status == "skipped"]
        assert len(skipped) >= 1


# ── render_digest_email (smoke tests from scheduler context) ─────────────────


class TestRenderDigestEmailSmoke:
    """Minimal smoke tests — comprehensive coverage lives in test_email_template.py."""

    @pytest.mark.unit
    def test_renders_narrative_in_html(self) -> None:
        html, _text = render_digest_email(narrative="Portfolio risk is high.")
        assert "Portfolio risk is high." in html
        assert "<html>" in html

    @pytest.mark.unit
    def test_empty_narrative_still_renders(self) -> None:
        html, text = render_digest_email(narrative="")
        assert isinstance(html, str) and len(html) > 0
        assert isinstance(text, str) and len(text) > 0

    @pytest.mark.unit
    def test_returns_tuple_of_two_strings(self) -> None:
        html, text = render_digest_email(narrative="test")
        assert isinstance(html, str)
        assert isinstance(text, str)
