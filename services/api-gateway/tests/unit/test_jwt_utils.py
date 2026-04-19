"""Unit tests for RS256 JWT utilities (jwt_utils.py + domain types)."""

from __future__ import annotations

import time

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa

pytestmark = pytest.mark.unit


# ── Fixture: real RSA-2048 keypair ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def rsa_keypair():
    """Generate a real RSA-2048 keypair for tests. Module-scoped for speed."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    return private_key, private_key.public_key()


@pytest.fixture(scope="module")
def kid(rsa_keypair):
    from api_gateway.oidc import rsa_key_id

    _, public_key = rsa_keypair
    return rsa_key_id(public_key)


# ── InternalJWTClaims domain type ──────────────────────────────────────────────


def test_internal_jwt_claims_frozen() -> None:
    """InternalJWTClaims is frozen — mutation raises FrozenInstanceError."""
    from api_gateway.domain import InternalJWTClaims

    now = int(time.time())
    claims = InternalJWTClaims(
        sub="user-123",
        tenant_id="tenant-456",
        oidc_sub="zitadel-sub",
        role="user",
        jti="jti-abc",
        iat=now,
        exp=now + 300,
        kid="kid-abc",
    )
    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        claims.sub = "other"  # type: ignore[misc]


def test_internal_jwt_claims_default_iss() -> None:
    """iss defaults to 'worldview-gateway'."""
    from api_gateway.domain import InternalJWTClaims

    now = int(time.time())
    claims = InternalJWTClaims(
        sub="user-123",
        tenant_id="tenant-456",
        oidc_sub="zitadel-sub",
        role="user",
        jti="jti-abc",
        iat=now,
        exp=now + 300,
        kid="kid-abc",
    )
    assert claims.iss == "worldview-gateway"


# ── JWT issuance ───────────────────────────────────────────────────────────────


def test_issue_user_jwt_claims(rsa_keypair, kid) -> None:
    """User JWT has correct structure: iss, sub, tenant_id, role=user, exp=iat+300."""
    from api_gateway.jwt_utils import decode_internal_jwt, issue_user_jwt

    private_key, public_key = rsa_keypair
    token = issue_user_jwt("user-1", "tenant-1", "zitadel-sub-1", private_key, kid)
    payload = decode_internal_jwt(token, public_key)

    assert payload["iss"] == "worldview-gateway"
    assert payload["sub"] == "user-1"
    assert payload["tenant_id"] == "tenant-1"
    assert payload["oidc_sub"] == "zitadel-sub-1"
    assert payload["role"] == "user"
    assert "jti" in payload
    assert payload["exp"] - payload["iat"] == 300


def test_issue_system_jwt_claims(rsa_keypair, kid) -> None:
    """System JWT has sub=system, role=system, exp=iat+60."""
    from api_gateway.jwt_utils import decode_internal_jwt, issue_system_jwt

    private_key, public_key = rsa_keypair
    token = issue_system_jwt("zitadel-sub-system", private_key, kid)
    payload = decode_internal_jwt(token, public_key)

    assert payload["sub"] == "system"
    assert payload["role"] == "system"
    assert payload["tenant_id"] == ""
    assert payload["exp"] - payload["iat"] == 60


def test_issue_public_jwt_claims(rsa_keypair, kid) -> None:
    """Public JWT has sub=system:api-gateway, nil UUIDs, role=system, exp=iat+60."""
    from api_gateway.jwt_utils import decode_internal_jwt, issue_public_jwt

    private_key, public_key = rsa_keypair
    token = issue_public_jwt(private_key, kid)
    payload = decode_internal_jwt(token, public_key)

    assert payload["iss"] == "worldview-gateway"
    assert payload["sub"] == "system:api-gateway"
    assert payload["user_id"] == "00000000-0000-0000-0000-000000000000"
    assert payload["tenant_id"] == "00000000-0000-0000-0000-000000000000"
    assert payload["role"] == "system"
    assert "jti" in payload
    assert payload["exp"] - payload["iat"] == 60


def test_decode_jwt_wrong_issuer(rsa_keypair, kid) -> None:
    """JWT with wrong iss raises InvalidTokenError."""
    import jwt as pyjwt
    from api_gateway.jwt_utils import decode_internal_jwt

    private_key, public_key = rsa_keypair
    now = int(time.time())
    # Manually encode with wrong issuer
    payload = {
        "iss": "wrong-issuer",
        "sub": "user-1",
        "tenant_id": "t1",
        "oidc_sub": "s",
        "role": "user",
        "jti": "jti-1",
        "iat": now,
        "exp": now + 300,
        "kid": kid,
    }
    token = pyjwt.encode(payload, private_key, algorithm="RS256", headers={"kid": kid})
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_internal_jwt(token, public_key)


def test_decode_jwt_expired(rsa_keypair, kid) -> None:
    """Expired JWT raises InvalidTokenError."""
    import jwt as pyjwt
    from api_gateway.jwt_utils import decode_internal_jwt

    private_key, public_key = rsa_keypair
    now = int(time.time())
    payload = {
        "iss": "worldview-gateway",
        "sub": "user-1",
        "tenant_id": "t1",
        "oidc_sub": "s",
        "role": "user",
        "jti": "jti-1",
        "iat": now - 400,
        "exp": now - 100,  # already expired
        "kid": kid,
    }
    token = pyjwt.encode(payload, private_key, algorithm="RS256", headers={"kid": kid})
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_internal_jwt(token, public_key)


def test_jti_uniqueness(rsa_keypair, kid) -> None:
    """Two issue_user_jwt calls produce different jti values."""
    from api_gateway.jwt_utils import decode_internal_jwt, issue_user_jwt

    private_key, public_key = rsa_keypair
    t1 = issue_user_jwt("u", "t", "s", private_key, kid)
    t2 = issue_user_jwt("u", "t", "s", private_key, kid)
    p1 = decode_internal_jwt(t1, public_key)
    p2 = decode_internal_jwt(t2, public_key)
    assert p1["jti"] != p2["jti"]


# ── JWKS utilities ─────────────────────────────────────────────────────────────


def test_rsa_key_id_deterministic(rsa_keypair) -> None:
    """rsa_key_id returns the same value on repeated calls."""
    from api_gateway.oidc import rsa_key_id

    _, public_key = rsa_keypair
    assert rsa_key_id(public_key) == rsa_key_id(public_key)


def test_build_jwks_contains_correct_fields(rsa_keypair, kid) -> None:
    """build_jwks_response returns JWKS with all required fields."""
    from api_gateway.oidc import build_jwks_response

    _, public_key = rsa_keypair
    jwks = build_jwks_response(public_key, kid)
    assert "keys" in jwks
    key_entry = jwks["keys"][0]
    for field in ("kty", "alg", "use", "kid", "n", "e"):
        assert field in key_entry, f"Missing field: {field}"
    assert key_entry["kty"] == "RSA"
    assert key_entry["alg"] == "RS256"
    assert key_entry["use"] == "sig"
    assert key_entry["kid"] == kid
