"""Tests for observability.startup_assert.

Covers PLAN-0093 Wave A-1 T-A-1-03 acceptance criteria:
    - When ``internal_jwt_skip_verification=True`` and ``APP_ENV`` is unset,
      ``assert_app_env_or_die`` raises ``RuntimeError`` AND logs a critical
      ``startup_security_check_failed`` event.
    - When either condition fails (skip off, or APP_ENV set), the helper is a
      no-op — it must not raise.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from observability.logging import configure_logging
from observability.startup_assert import assert_app_env_or_die


@pytest.fixture
def clean_app_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """Ensure tests start with ``APP_ENV`` unset regardless of the host env.

    Local dev shells may already export ``APP_ENV`` for compose, so the unset
    cases must explicitly clear it.  Yielded so individual tests can set the
    value through the same monkeypatch handle.
    """
    monkeypatch.delenv("APP_ENV", raising=False)
    yield monkeypatch


class TestAssertAppEnvOrDie:
    """Boot-time guard against the JWT-skip + APP_ENV-unset combo."""

    def test_app_env_unset_with_skip_verification_raises(
        self,
        clean_app_env: pytest.MonkeyPatch,  # — fixture clears APP_ENV
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The critical-path failure: BOTH conditions hold → boot must abort.

        We call ``configure_logging`` first so structlog routes through the
        stdlib handler that pytest captures via ``capsys``.  Without this the
        default structlog print-logger writes straight to the test runner's
        own stderr buffer and the assertion below never sees it.
        """
        # JSON output so the structured event keys are easy to find via substring.
        configure_logging("rag-chat", level="CRITICAL", json=True)

        with pytest.raises(RuntimeError, match="BLOCKING SECURITY"):
            assert_app_env_or_die(
                service_name="rag-chat",
                internal_jwt_skip_verification=True,
            )

        # The structured event must be emitted BEFORE the raise so log-based
        # alerts (Loki / Sentry) fire even when the process crashes immediately.
        # Substring check on the JSON line is sufficient — we don't care about
        # the exact field ordering structlog chose.
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "startup_security_check_failed" in combined, (
            f"missing 'startup_security_check_failed' in captured output:\n"
            f"stdout={captured.out!r}\nstderr={captured.err!r}"
        )

    def test_app_env_set_with_skip_verification_does_not_raise(
        self,
        clean_app_env: pytest.MonkeyPatch,
    ) -> None:
        """Dev/test environments may legitimately skip JWT verification."""
        clean_app_env.setenv("APP_ENV", "development")
        # Must not raise — APP_ENV is set, so the operator has acknowledged
        # the environment classification.
        assert_app_env_or_die(
            service_name="rag-chat",
            internal_jwt_skip_verification=True,
        )

    def test_app_env_unset_without_skip_verification_does_not_raise(
        self,
        clean_app_env: pytest.MonkeyPatch,  # — fixture clears APP_ENV
    ) -> None:
        """Default safe config (skip=False, no APP_ENV) is fine — no-op."""
        assert_app_env_or_die(
            service_name="api-gateway",
            internal_jwt_skip_verification=False,
        )

    def test_whitespace_only_app_env_is_treated_as_unset(
        self,
        clean_app_env: pytest.MonkeyPatch,
    ) -> None:
        """``APP_ENV='   '`` is functionally unset and must trip the guard."""
        clean_app_env.setenv("APP_ENV", "   ")
        with pytest.raises(RuntimeError, match="BLOCKING SECURITY"):
            assert_app_env_or_die(
                service_name="nlp-pipeline",
                internal_jwt_skip_verification=True,
            )

    def test_custom_app_env_var_name_is_honoured(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The helper allows overriding the env-var name for unit testing."""
        # Use a unique variable name that is guaranteed unset so the test is
        # hermetic regardless of the host env.
        monkeypatch.delenv("WORLDVIEW_TEST_ENV_SENTINEL", raising=False)
        with pytest.raises(RuntimeError, match="BLOCKING SECURITY"):
            assert_app_env_or_die(
                service_name="alert",
                internal_jwt_skip_verification=True,
                app_env_var="WORLDVIEW_TEST_ENV_SENTINEL",
            )

        # And the inverse: setting the custom var clears the guard.
        monkeypatch.setenv("WORLDVIEW_TEST_ENV_SENTINEL", "test")
        assert_app_env_or_die(
            service_name="alert",
            internal_jwt_skip_verification=True,
            app_env_var="WORLDVIEW_TEST_ENV_SENTINEL",
        )
