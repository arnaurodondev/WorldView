"""Unit tests for rag-chat service Settings (F-007 + F-014 + PLAN-0084 A-1/A-2)."""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.unit


# ── PLAN-0084 A-1: Citation cron settings ────────────────────────────────────


def _make_settings(**kwargs):  # type: ignore[no-untyped-def]
    """Convenience: build Settings with test defaults."""
    from rag_chat.config import Settings

    base = {
        "database_url": "postgresql+asyncpg://test:test@localhost:5432/test_rag_db",
        "s1_internal_token": "test-token",
        "_env_file": None,
    }
    base.update(kwargs)
    return Settings(**base)  # type: ignore[arg-type]


def test_citation_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """All citation cron fields default to documented values (PLAN-0084 A-1 T-A-1-01)."""
    for key in list(os.environ):
        if key.startswith("RAG_CHAT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

    s = _make_settings()
    assert s.citation_cron_enabled is False
    assert s.citation_judge_provider == "deepinfra"
    assert s.citation_min_samples == 10
    assert s.citation_call_timeout_s == 15.0
    assert s.citation_run_budget_s == 600.0


def test_completion_model_default_is_real_deepinfra_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEF-035: the completion_model default must be a model that exists on DeepInfra.

    The previous default ``deepseek-ai/DeepSeek-V4-Flash-Thinking`` 404s on
    DeepInfra — an unset ``RAG_CHAT_COMPLETION_MODEL`` would break completions.
    The default now matches prod (``openai/gpt-oss-120b``).
    """
    for key in list(os.environ):
        if key.startswith("RAG_CHAT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

    s = _make_settings()
    assert s.completion_model == "openai/gpt-oss-120b"
    # Regression guard: the known-404 model must never be the default again.
    assert "DeepSeek-V4-Flash-Thinking" not in s.completion_model


def test_citation_judge_provider_validates_enum(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid citation_judge_provider raises ValidationError."""
    for key in list(os.environ):
        if key.startswith("RAG_CHAT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

    with pytest.raises(ValidationError):
        _make_settings(citation_judge_provider="unknown_provider")


def test_citation_call_timeout_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    """citation_call_timeout_s must be > 0 and ≤ 120."""
    for key in list(os.environ):
        if key.startswith("RAG_CHAT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

    with pytest.raises(ValidationError):
        _make_settings(citation_call_timeout_s=0.0)

    with pytest.raises(ValidationError):
        _make_settings(citation_call_timeout_s=121.0)

    # Valid boundary
    s = _make_settings(citation_call_timeout_s=120.0)
    assert s.citation_call_timeout_s == 120.0


# ── PLAN-0084 A-2: Circuit-breaker settings ───────────────────────────────────


def test_cb_cool_down_default_is_120(monkeypatch: pytest.MonkeyPatch) -> None:
    """cb_cool_down_seconds defaults to 120 (was 3600 before PLAN-0084 A-2)."""
    for key in list(os.environ):
        if key.startswith("RAG_CHAT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

    s = _make_settings()
    assert s.cb_cool_down_seconds == 120


def test_cb_probe_ttl_default_is_5(monkeypatch: pytest.MonkeyPatch) -> None:
    """cb_probe_ttl_seconds defaults to 5."""
    for key in list(os.environ):
        if key.startswith("RAG_CHAT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

    s = _make_settings()
    assert s.cb_probe_ttl_seconds == 5


def test_cb_cool_down_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    """cb_cool_down_seconds must be in [10, 3600]."""
    for key in list(os.environ):
        if key.startswith("RAG_CHAT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

    with pytest.raises(ValidationError):
        _make_settings(cb_cool_down_seconds=9)  # below min

    with pytest.raises(ValidationError):
        _make_settings(cb_cool_down_seconds=3601)  # above max


def test_skip_verification_blocked_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-007: internal_jwt_skip_verification=True MUST raise in production."""
    for key in list(os.environ):
        if key.startswith("RAG_CHAT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APP_ENV", "production")

    from rag_chat.config import Settings

    # S-005: message mentions "outside safe environments" (F-007)
    with pytest.raises(ValidationError, match="MUST NOT be enabled outside safe environments"):
        Settings(
            database_url="postgresql+asyncpg://test:test@localhost:5432/test_rag_db",
            s1_internal_token="test-token",
            internal_jwt_skip_verification=True,
            _env_file=None,
        )


def test_skip_verification_allowed_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-007: internal_jwt_skip_verification=True is allowed in non-production."""
    for key in list(os.environ):
        if key.startswith("RAG_CHAT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APP_ENV", "development")

    from rag_chat.config import Settings

    settings = Settings(
        database_url="postgresql+asyncpg://test:test@localhost:5432/test_rag_db",
        s1_internal_token="test-token",
        internal_jwt_skip_verification=True,
        _env_file=None,
    )
    assert settings.internal_jwt_skip_verification is True


def test_empty_database_url_read_coerced_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-014: Empty/whitespace DATABASE_URL_READ is coerced to None."""
    for key in list(os.environ):
        if key.startswith("RAG_CHAT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

    from rag_chat.config import Settings

    settings = Settings(
        database_url="postgresql+asyncpg://test:test@localhost:5432/test_rag_db",
        s1_internal_token="test-token",
        database_url_read="   ",  # whitespace-only
        _env_file=None,
    )
    assert settings.database_url_read is None


def test_whitespace_database_url_read_env_coerced_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-014: RAG_CHAT_DATABASE_URL_READ=' ' is coerced to None."""
    for key in list(os.environ):
        if key.startswith("RAG_CHAT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("RAG_CHAT_DATABASE_URL_READ", "  ")

    from rag_chat.config import Settings

    settings = Settings(
        database_url="postgresql+asyncpg://test:test@localhost:5432/test_rag_db",
        s1_internal_token="test-token",
        _env_file=None,
    )
    assert settings.database_url_read is None


def test_valid_database_url_read_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-014: Non-empty database_url_read is preserved."""
    for key in list(os.environ):
        if key.startswith("RAG_CHAT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

    from rag_chat.config import Settings

    settings = Settings(
        database_url="postgresql+asyncpg://test:test@localhost:5432/test_rag_db",
        s1_internal_token="test-token",
        database_url_read="postgresql+asyncpg://reader:reader@localhost:5432/test_rag_db",
        _env_file=None,
    )
    assert settings.database_url_read is not None
    assert "reader" in settings.database_url_read.get_secret_value()


# ── PLAN-0079 Wave C: Trust scoring weight settings ───────────────────────────


def test_trust_weight_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLAN-0079 Wave C: trust_w_* settings default to 0.4/0.1/0.1."""
    for key in list(os.environ):
        if key.startswith("RAG_CHAT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

    s = _make_settings()
    assert s.trust_w_source == 0.4
    assert s.trust_w_corroboration == 0.1
    assert s.trust_w_extraction == 0.1


def test_trust_weight_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLAN-0079 Wave C: trust_w_* can be overridden via env vars."""
    for key in list(os.environ):
        if key.startswith("RAG_CHAT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("RAG_CHAT_TRUST_W_SOURCE", "0.6")
    monkeypatch.setenv("RAG_CHAT_TRUST_W_CORROBORATION", "0.2")
    monkeypatch.setenv("RAG_CHAT_TRUST_W_EXTRACTION", "0.15")

    s = _make_settings()
    assert s.trust_w_source == pytest.approx(0.6)
    assert s.trust_w_corroboration == pytest.approx(0.2)
    assert s.trust_w_extraction == pytest.approx(0.15)
