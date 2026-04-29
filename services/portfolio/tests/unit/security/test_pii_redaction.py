"""Unit tests for PII / secret redaction (PLAN-0052 Wave D / T-D-4-04).

Covers each pattern in ``portfolio.security.pii_redaction`` plus
boundary cases: idempotency on already-redacted text, no-op on plain
text, recursive JSON walking.
"""

from __future__ import annotations

import pytest
from portfolio.security.pii_redaction import redact, redact_json

pytestmark = [pytest.mark.unit]


# ── Bearer / JWT ─────────────────────────────────────────────────────────────


def test_redacts_bearer_token() -> None:
    text = "curl -H 'Authorization: Bearer abcdef0123456789ABCDEF' https://x"
    out = redact(text)
    assert out is not None
    assert "abcdef0123456789ABCDEF" not in out
    # Either the Bearer-prefix replacement or the header-line replacement
    # must have fired; both fully scrub the secret.
    assert "[REDACTED:" in out


def test_redacts_raw_jwt() -> None:
    # Real-shaped JWT (header.payload.signature, base64url segments).
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.dQw4w9WgXcQ_secretsig"
    out = redact(f"token={jwt}")
    assert out is not None
    assert jwt not in out
    assert "[REDACTED:JWT]" in out


# ── API key ──────────────────────────────────────────────────────────────────


def test_redacts_api_key_assignment() -> None:
    out = redact('api_key="sk-1234567890abcdef1234567890"')
    assert out is not None
    assert "sk-1234567890abcdef1234567890" not in out
    # Keeps the "api_key" keyword so support staff can see what was scrubbed.
    assert "api_key" in out
    assert "[REDACTED:API_KEY]" in out


def test_redacts_api_key_with_dash_and_caps() -> None:
    out = redact("API-Key: ABCDEF1234567890ABCDEF1234567890")
    assert out is not None
    assert "ABCDEF1234567890ABCDEF1234567890" not in out


# ── Header lines ─────────────────────────────────────────────────────────────


def test_redacts_authorization_header_line() -> None:
    out = redact("authorization: Basic dXNlcjpwYXNz")
    assert out is not None
    assert "dXNlcjpwYXNz" not in out
    assert "authorization" in out  # keyword preserved


def test_redacts_cookie_header() -> None:
    out = redact("cookie: session=abc123sessiondata")
    assert out is not None
    assert "abc123sessiondata" not in out


# ── Email / CC / SSN ─────────────────────────────────────────────────────────


def test_redacts_email_in_free_text() -> None:
    out = redact("contact me at john.doe+spam@example.com please")
    assert out is not None
    assert "john.doe+spam@example.com" not in out
    assert "[REDACTED:EMAIL]" in out


def test_redacts_credit_card_with_dashes() -> None:
    out = redact("My card is 4111-1111-1111-1111")
    assert out is not None
    assert "4111-1111-1111-1111" not in out
    assert "[REDACTED:CC]" in out


def test_redacts_credit_card_no_dashes() -> None:
    out = redact("4111111111111111")
    assert out is not None
    assert "4111111111111111" not in out


def test_redacts_ssn() -> None:
    out = redact("SSN: 123-45-6789")
    assert out is not None
    assert "123-45-6789" not in out
    assert "[REDACTED:SSN]" in out


# ── Boundary cases ───────────────────────────────────────────────────────────


def test_no_op_on_plain_text() -> None:
    plain = "I cannot find the watchlist button on the dashboard"
    assert redact(plain) == plain


def test_no_op_on_empty_string() -> None:
    assert redact("") == ""


def test_passes_none_through() -> None:
    assert redact(None) is None


def test_idempotent_on_already_redacted_text() -> None:
    # Run redact twice — the second pass must not double-redact or alter
    # the marker. This guards against accidental "[REDACTED:JWT]" being
    # caught by a later pattern.
    once = redact("Bearer abcdef0123456789ABCDEF and email a@b.com")
    twice = redact(once)
    assert once == twice


def test_does_not_redact_short_random_strings() -> None:
    # 8-char random string should not be scrubbed — too short to be a
    # plausible API key (regex requires ≥16).
    assert redact("token=abcd1234") == "token=abcd1234"


# ── redact_json (recursive) ──────────────────────────────────────────────────


def test_redact_json_walks_dict_and_list() -> None:
    payload = {
        "level": "error",
        "message": "Auth failed for a@b.com using Bearer abcdef0123456789ABCDEF",
        "context": {"headers": ["cookie: session=verysecretstuffhere"]},
        "count": 3,  # non-string passes through
        "ok": False,
    }
    out = redact_json(payload)
    # Non-string scalars untouched
    assert out["count"] == 3
    assert out["ok"] is False
    # Strings recursively scrubbed
    assert "a@b.com" not in out["message"]
    assert "abcdef0123456789ABCDEF" not in out["message"]
    assert "verysecretstuffhere" not in out["context"]["headers"][0]


def test_redact_json_passes_scalars_through() -> None:
    assert redact_json(42) == 42
    assert redact_json(None) is None
    assert redact_json(True) is True
