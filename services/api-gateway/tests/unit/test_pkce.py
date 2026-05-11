"""Unit tests for PKCE utilities (api_gateway.pkce)."""

from __future__ import annotations

import base64
import hashlib
import re
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


# ── RFC 7636 test vector ──────────────────────────────────────────────────────
# code_verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
# code_challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
_RFC_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
_RFC_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_pkce_challenge_s256() -> None:
    """generate_code_challenge produces correct S256 hash (RFC 7636 test vector)."""
    from api_gateway.pkce import generate_code_challenge

    assert generate_code_challenge(_RFC_VERIFIER) == _RFC_CHALLENGE


def test_pkce_challenge_no_padding() -> None:
    """Output of generate_code_challenge must not contain '=' padding."""
    from api_gateway.pkce import generate_code_challenge, generate_code_verifier

    verifier = generate_code_verifier()
    challenge = generate_code_challenge(verifier)
    assert "=" not in challenge


def test_pkce_challenge_matches_sha256() -> None:
    """Verify S256 computation matches a manual reference implementation."""
    from api_gateway.pkce import generate_code_challenge

    verifier = "test-verifier-string"
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode().rstrip("=")
    assert generate_code_challenge(verifier) == expected


def test_code_verifier_length() -> None:
    """generate_code_verifier produces exactly 43 characters."""
    from api_gateway.pkce import generate_code_verifier

    verifier = generate_code_verifier()
    assert len(verifier) == 43


def test_state_is_uuid4_format() -> None:
    """generate_state returns a UUID4-format string."""
    from api_gateway.pkce import generate_state

    state = generate_state()
    _uuid4_re = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
    assert _uuid4_re.match(state), f"{state!r} is not a UUID4"


@pytest.mark.asyncio
async def test_retrieve_deletes_key() -> None:
    """Second retrieve_and_delete_pkce_state call for same state returns None."""
    from api_gateway.pkce import retrieve_and_delete_pkce_state

    # Atomic GETDEL: first call returns the stored value; second call returns None
    valkey = MagicMock()
    valkey.getdel = AsyncMock(side_effect=["my-verifier", None])

    result1 = await retrieve_and_delete_pkce_state(valkey, "test-state")
    result2 = await retrieve_and_delete_pkce_state(valkey, "test-state")

    assert result1 == "my-verifier"
    assert result2 is None


@pytest.mark.asyncio
async def test_retrieve_returns_none_on_missing_key() -> None:
    """retrieve_and_delete_pkce_state returns None for unknown state."""
    from api_gateway.pkce import retrieve_and_delete_pkce_state

    valkey = MagicMock()
    valkey.getdel = AsyncMock(return_value=None)

    result = await retrieve_and_delete_pkce_state(valkey, "unknown-state")
    assert result is None


@pytest.mark.asyncio
async def test_store_pkce_state_raises_on_none_valkey() -> None:
    """store_pkce_state raises RuntimeError when Valkey is None (fail-closed)."""
    from api_gateway.pkce import store_pkce_state

    with pytest.raises(RuntimeError, match="valkey_unavailable"):
        await store_pkce_state(None, "state", "verifier")


@pytest.mark.asyncio
async def test_store_pkce_state_raises_on_valkey_error() -> None:
    """store_pkce_state raises RuntimeError if Valkey raises an exception."""
    from api_gateway.pkce import store_pkce_state

    valkey = MagicMock()
    valkey.set = AsyncMock(side_effect=ConnectionError("timeout"))

    with pytest.raises(RuntimeError, match="valkey_unavailable"):
        await store_pkce_state(valkey, "state", "verifier")
