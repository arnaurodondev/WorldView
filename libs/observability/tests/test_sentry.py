"""Unit tests for observability.sentry — init_sentry, SentrySettings, _before_send."""

from __future__ import annotations

import hashlib
from time import monotonic
from typing import Any
from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestSentrySettings:
    def test_disabled_by_default(self) -> None:
        from observability.sentry import SentrySettings

        s = SentrySettings()
        assert s.enabled is False

    def test_enabled_without_dsn_raises(self) -> None:
        from pydantic import ValidationError

        from observability.sentry import SentrySettings

        with pytest.raises(ValidationError, match="SENTRY_DSN required"):
            SentrySettings(enabled=True, dsn=None)

    def test_enabled_with_empty_dsn_string_raises(self) -> None:
        """BP-179: pydantic-settings parses SENTRY_DSN= as SecretStr(''), not None."""
        from pydantic import SecretStr, ValidationError

        from observability.sentry import SentrySettings

        with pytest.raises(ValidationError, match="SENTRY_DSN required"):
            SentrySettings(enabled=True, dsn=SecretStr(""))

    def test_enabled_with_dsn_accepts(self) -> None:
        from pydantic import SecretStr

        from observability.sentry import SentrySettings

        s = SentrySettings(enabled=True, dsn=SecretStr("https://key@sentry.io/123"))
        assert s.enabled is True


@pytest.mark.unit
class TestInitSentry:
    def test_disabled_returns_false(self) -> None:
        from observability.sentry import SentrySettings, init_sentry

        result = init_sentry("test-svc", settings=SentrySettings(enabled=False))
        assert result is False

    def test_disabled_does_not_call_sentry_init(self) -> None:
        from observability.sentry import SentrySettings, init_sentry

        # sentry_sdk is imported lazily inside init_sentry; patch the top-level module.
        with patch("sentry_sdk.init") as mock_init:
            result = init_sentry("test-svc", settings=SentrySettings(enabled=False))
        assert result is False
        mock_init.assert_not_called()

    def test_enabled_with_dsn_returns_true(self) -> None:
        from pydantic import SecretStr

        from observability.sentry import SentrySettings, init_sentry

        settings = SentrySettings(
            enabled=True,
            dsn=SecretStr("https://key@o123.ingest.sentry.io/456"),
        )
        with patch("sentry_sdk.init"), patch("sentry_sdk.set_tag"):
            result = init_sentry("api-gateway", settings=settings)
        assert result is True

    def test_enabled_calls_init_with_expected_kwargs(self) -> None:
        from pydantic import SecretStr

        from observability.sentry import SentrySettings, init_sentry

        settings = SentrySettings(
            enabled=True,
            dsn=SecretStr("https://key@o123.ingest.sentry.io/456"),
        )
        with patch("sentry_sdk.init") as mock_init, patch("sentry_sdk.set_tag"):
            init_sentry("api-gateway", settings=settings)

        mock_init.assert_called_once()
        call_kwargs = mock_init.call_args.kwargs
        assert call_kwargs["attach_stacktrace"] is True
        assert call_kwargs["send_default_pii"] is False

    def test_init_failure_returns_false(self) -> None:
        from pydantic import SecretStr

        from observability.sentry import SentrySettings, init_sentry

        settings = SentrySettings(
            enabled=True,
            dsn=SecretStr("https://key@o123.ingest.sentry.io/456"),
        )
        with patch("sentry_sdk.init", side_effect=RuntimeError("network down")):
            result = init_sentry("api-gateway", settings=settings)
        assert result is False

    def test_sets_service_tag_when_initialised(self) -> None:
        from pydantic import SecretStr

        from observability.sentry import SentrySettings, init_sentry

        settings = SentrySettings(
            enabled=True,
            dsn=SecretStr("https://key@o123.ingest.sentry.io/456"),
        )
        with patch("sentry_sdk.init"), patch("sentry_sdk.set_tag") as mock_tag:
            init_sentry("rag-chat", settings=settings)
        mock_tag.assert_called_once_with("service", "rag-chat")


@pytest.mark.unit
class TestBeforeSend:
    def _make_event(self, **overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "request": {
                "url": "/v1/dashboard",
                "headers": {},
                "cookies": {},
                "query_string": "",
            },
            "exception": {"values": [{"type": "ValueError"}]},
            "transaction": "/v1/dashboard",
        }
        base.update(overrides)
        return base

    def test_strips_authorization_header(self) -> None:
        from observability.sentry import _before_send

        event = self._make_event()
        event["request"]["headers"] = {"authorization": "Bearer secret", "content-type": "application/json"}
        result = _before_send(event, {})
        assert result is not None
        assert "authorization" not in result["request"]["headers"]
        assert "content-type" in result["request"]["headers"]

    def test_strips_x_internal_jwt_header(self) -> None:
        from observability.sentry import _before_send

        event = self._make_event()
        event["request"]["headers"] = {"x-internal-jwt": "eyJ..."}
        result = _before_send(event, {})
        assert result is not None
        assert "x-internal-jwt" not in result["request"]["headers"]

    def test_hashes_user_email(self) -> None:
        from observability.sentry import _before_send

        email = "sam@worldview.local"
        event = self._make_event(user={"email": email, "id": "u1"})
        result = _before_send(event, {})
        assert result is not None
        expected = hashlib.sha256(email.encode()).hexdigest()
        assert result["user"]["email"] == expected
        assert result["user"]["id"] == "u1"

    def test_drops_sensitive_keys_from_extra(self) -> None:
        from observability.sentry import _before_send

        event = self._make_event(extra={"jwt_token": "abc", "user_id": "u1", "api_key": "secret"})
        result = _before_send(event, {})
        assert result is not None
        assert "jwt_token" not in result["extra"]
        assert "api_key" not in result["extra"]
        assert result["extra"]["user_id"] == "u1"

    def test_drops_query_string(self) -> None:
        from observability.sentry import _before_send

        event = self._make_event()
        event["request"]["query_string"] = "q=AAPL&page=1"
        result = _before_send(event, {})
        assert result is not None
        assert "query_string" not in result["request"]

    def test_redacts_instrument_ticker_in_url(self) -> None:
        from observability.sentry import _before_send

        event = self._make_event()
        event["request"]["url"] = "/v1/instruments/AAPL/ownership"
        result = _before_send(event, {})
        assert result is not None
        assert "AAPL" not in result["request"]["url"]
        assert "<redacted>" in result["request"]["url"]

    def test_redacts_breadcrumb_urls(self) -> None:
        from observability.sentry import _before_send

        event = self._make_event(
            breadcrumbs={
                "values": [
                    {"type": "http", "data": {"url": "/v1/instruments/NVDA/fundamentals"}},
                    {"type": "http", "data": {"url": "/v1/dashboard"}},
                ]
            }
        )
        result = _before_send(event, {})
        assert result is not None
        crumbs = result["breadcrumbs"]["values"]
        assert "NVDA" not in crumbs[0]["data"]["url"]
        assert "<redacted>" in crumbs[0]["data"]["url"]
        assert crumbs[1]["data"]["url"] == "/v1/dashboard"


@pytest.mark.unit
class TestFingerprintRateLimit:
    def _reset_fingerprint_counts(self) -> None:
        from observability.sentry import _fingerprint_counts

        _fingerprint_counts.clear()

    def _make_event(self, fp: str) -> dict[str, Any]:
        return {
            "fingerprint": [fp],
            "exception": {"values": [{"type": "ValueError"}]},
            "transaction": "/test",
            "request": {},
        }

    def test_drops_excess_events_for_same_fingerprint(self) -> None:
        from observability.sentry import _before_send, _rl_config

        self._reset_fingerprint_counts()
        original_max = _rl_config.max_events_per_hour
        _rl_config.max_events_per_hour = 3

        retained = sum(1 for _ in range(10) if _before_send(self._make_event("fp-excess"), {}) is not None)
        assert retained == 3

        _rl_config.max_events_per_hour = original_max
        self._reset_fingerprint_counts()

    def test_independent_fingerprints_not_throttled(self) -> None:
        from observability.sentry import _before_send, _rl_config

        self._reset_fingerprint_counts()
        original_max = _rl_config.max_events_per_hour
        _rl_config.max_events_per_hour = 5

        retained_a = sum(1 for _ in range(5) if _before_send(self._make_event("fp-a"), {}) is not None)
        retained_b = sum(1 for _ in range(5) if _before_send(self._make_event("fp-b"), {}) is not None)
        assert retained_a == 5
        assert retained_b == 5

        _rl_config.max_events_per_hour = original_max
        self._reset_fingerprint_counts()

    def test_aged_stamps_evicted_after_window(self) -> None:
        """Stamps older than _FINGERPRINT_WINDOW_SEC must be evicted so the window slides."""
        from observability.sentry import (
            _FINGERPRINT_WINDOW_SEC,
            _before_send,
            _fingerprint_counts,
            _rl_config,
        )

        self._reset_fingerprint_counts()
        original_max = _rl_config.max_events_per_hour
        _rl_config.max_events_per_hour = 2

        # Fire max_events to fill the bucket
        for _ in range(2):
            _before_send(self._make_event("fp-age"), {})

        # Manually age out the stamps by setting them to a time past the window
        expired_time = monotonic() - _FINGERPRINT_WINDOW_SEC - 1.0
        counts = _fingerprint_counts.get("fp-age")
        if counts is not None:
            for i in range(len(counts)):
                counts[i] = expired_time

        # One more event should now be retained (window slid past aged entries)
        result = _before_send(self._make_event("fp-age"), {})
        assert result is not None

        _rl_config.max_events_per_hour = original_max
        self._reset_fingerprint_counts()
