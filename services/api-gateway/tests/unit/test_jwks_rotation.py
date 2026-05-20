"""Unit tests for W1-05 (BUG-005) — kid-based JWKS rotation.

S9 must:
  1. Stamp every issued internal JWT with a ``kid`` header equal to
     ``settings.jwt_key_version`` so backends can refresh JWKS on miss.
  2. Expose ``/internal/jwks`` as a ``{"keys": [...]}`` array where every entry
     carries a non-empty ``kid`` (current key + any operator-populated
     ``app.state.previous_jwks`` entries for the grace window).

These tests do NOT exercise the full gateway lifespan — they build the FastAPI
app via ``create_app(...)`` and seed ``app.state`` directly the way the
existing ``conftest.py`` already does for other tests.
"""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def rsa_keypair() -> tuple[Any, Any]:
    """Real RSA-2048 keypair for signing internal JWTs in this test module."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture
def app_with_jwks(rsa_keypair):
    """Build S9 app with RSA key wired into app.state.

    Mirrors what lifespan does but synchronously — we don't want to trigger
    real OIDC discovery / Valkey / outbound clients in a unit test.
    """
    from api_gateway.oidc import build_jwks_response

    from tests.conftest import _build_app, _mock_settings  # type: ignore[attr-defined]

    settings = _mock_settings()
    application, _ = _build_app(settings, inject_user_from_bearer=False)

    private_key, public_key = rsa_keypair
    application.state.rsa_private_key = private_key
    application.state.rsa_public_key = public_key
    # Default JWT_KEY_VERSION is "v1" per Settings — pin it here so the test
    # is robust to a future settings default change.
    application.state.rsa_kid = "v1"
    application.state.internal_jwks = build_jwks_response(public_key, "v1")
    application.state.previous_jwks = []
    return application


# ── /internal/jwks shape ──────────────────────────────────────────────────────


def test_jwks_endpoint_returns_keys_with_kid(app_with_jwks) -> None:
    """GET /internal/jwks → ``{"keys": [{...kid: "v1"...}]}``.

    W1-05 acceptance: every key entry must carry a non-empty ``kid`` so
    backends can populate their ``keys_by_kid`` lookup table.
    """
    client = TestClient(app_with_jwks)
    resp = client.get("/internal/jwks")

    assert resp.status_code == 200
    body = resp.json()
    assert "keys" in body
    assert isinstance(body["keys"], list)
    assert len(body["keys"]) >= 1
    for entry in body["keys"]:
        assert entry.get("kid"), f"missing/empty kid on JWK entry: {entry}"
        assert entry.get("kty") == "RSA"
        assert entry.get("alg") == "RS256"


def test_jwks_endpoint_includes_previous_keys_during_grace(app_with_jwks) -> None:
    """Operator-populated ``previous_jwks`` entries appear in the response (capped at 3)."""
    # Simulate a key rotation: operator appends the outgoing JWK to previous_jwks.
    # Five entries to verify the cap (response should include only 3 previous).
    app_with_jwks.state.previous_jwks = [
        {"kty": "RSA", "alg": "RS256", "use": "sig", "kid": f"v0-{i}", "n": "AA", "e": "AQAB"} for i in range(5)
    ]

    client = TestClient(app_with_jwks)
    resp = client.get("/internal/jwks")

    assert resp.status_code == 200
    kids = [entry["kid"] for entry in resp.json()["keys"]]
    # 1 current + 3 previous (capped) = 4 total
    assert len(kids) == 4
    assert "v1" in kids
    # First 3 of the previous_jwks list should be present
    assert "v0-0" in kids
    assert "v0-1" in kids
    assert "v0-2" in kids
    # Beyond the cap → excluded
    assert "v0-3" not in kids
    assert "v0-4" not in kids


def test_jwks_endpoint_returns_503_when_not_initialized(app_with_jwks) -> None:
    """If ``internal_jwks`` is unset (early startup race) → 503."""
    app_with_jwks.state.internal_jwks = None
    client = TestClient(app_with_jwks)
    resp = client.get("/internal/jwks")
    assert resp.status_code == 503


# ── Issued JWT carries kid header ─────────────────────────────────────────────


def test_issued_user_jwt_has_kid_header(rsa_keypair) -> None:
    """``issue_user_jwt`` stamps the configured kid into the JWT header.

    W1-05 acceptance: backends decode the unverified header to look up the
    correct public key in their kid map; without a kid the refresh-on-miss
    path falls back to the default ``"v1"`` (back-compat with un-upgraded S9).
    """
    from api_gateway.jwt_utils import issue_user_jwt

    private_key, _ = rsa_keypair
    token = issue_user_jwt(
        user_id="user-1",
        tenant_id="tenant-1",
        oidc_sub="zitadel-sub-1",
        private_key=private_key,
        kid="v1",
    )
    header = jwt.get_unverified_header(token)
    assert header.get("kid") == "v1"
    assert header.get("alg") == "RS256"


def test_issued_system_jwt_has_kid_header(rsa_keypair) -> None:
    """System JWT (S9 → S1 provisioning) also carries the kid header."""
    from api_gateway.jwt_utils import issue_system_jwt

    private_key, _ = rsa_keypair
    token = issue_system_jwt(
        oidc_sub="zitadel-sub-system",
        private_key=private_key,
        kid="v2-test-rotation",
    )
    header = jwt.get_unverified_header(token)
    assert header.get("kid") == "v2-test-rotation"


def test_issued_service_jwt_has_kid_header(rsa_keypair) -> None:
    """Service-account JWT (workers) carries the kid header."""
    from api_gateway.jwt_utils import issue_service_jwt

    private_key, _ = rsa_keypair
    token = issue_service_jwt(
        service_name="nlp-pipeline-price-impact",
        private_key=private_key,
        kid="v1",
    )
    header = jwt.get_unverified_header(token)
    assert header.get("kid") == "v1"


def test_decoded_payload_keeps_kid_claim(rsa_keypair) -> None:
    """Sanity: the ``kid`` field also lives inside the payload (existing contract)."""
    from api_gateway.jwt_utils import decode_internal_jwt, issue_user_jwt

    private_key, public_key = rsa_keypair
    token = issue_user_jwt("u", "t", "s", private_key, "v1")
    payload = decode_internal_jwt(token, public_key)
    # Issued payload includes "kid" claim (separate from JWT header kid) —
    # legacy contract preserved by this task.
    # JWT timestamp arithmetic is tolerant — 1 second slop.
    assert int(time.time()) - payload["iat"] < 5
    assert payload["kid"] == "v1"
