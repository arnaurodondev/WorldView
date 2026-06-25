"""E2E — rag-chat (S8) internal-JWT security boundary.

The audit (2026-06-22) flags that S8 has no e2e tier and that the mocked
unit/integration conftest decodes JWTs with ``verify_signature=False``, so the
*real* rejection paths of ``InternalJWTMiddleware`` are never exercised end to
end. This module drives the production app (fail-closed, real RS256 public key)
through ``httpx.ASGITransport`` and asserts the full rejection matrix on a real
proxied route, plus a non-spoofable identity property.

No infrastructure required (in-process ASGI), but marked ``integration`` so it
runs in the e2e/integration tier rather than the fast unit lane.
"""

from __future__ import annotations

import time

import jwt as _jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

pytestmark = pytest.mark.integration

# A guarded route behind the middleware. POST /api/v1/chat requires a valid JWT;
# the middleware rejects before the route body ever runs.
_GUARDED_PATH = "/api/v1/chat"
_GUARDED_BODY = {"message": "hello"}


async def test_no_token_rejected_401(unauth_client) -> None:
    """No X-Internal-JWT header → 401 (middleware fails closed before the route)."""
    resp = await unauth_client.post(_GUARDED_PATH, json=_GUARDED_BODY)
    assert resp.status_code == 401


async def test_malformed_token_rejected_401(client) -> None:
    """A non-JWT garbage token → 401 (decode error in real-verification path)."""
    resp = await client.post(
        _GUARDED_PATH,
        json=_GUARDED_BODY,
        headers={"X-Internal-JWT": "not-a-jwt"},
    )
    assert resp.status_code == 401


async def test_tampered_signature_rejected_401(client, mint_token) -> None:
    """A valid token whose signature is corrupted → 401 (RS256 verification fails)."""
    token = mint_token()
    # Flip the final signature segment so the RS256 check fails.
    head, payload, sig = token.split(".")
    tampered = f"{head}.{payload}.{sig[:-4]}AAAA"
    resp = await client.post(
        _GUARDED_PATH,
        json=_GUARDED_BODY,
        headers={"X-Internal-JWT": tampered},
    )
    assert resp.status_code == 401


async def test_wrong_signing_key_rejected_401(client, mint_token) -> None:
    """A well-formed RS256 token signed by a DIFFERENT key → 401."""
    # A fresh, unrelated RSA key the server does not know about.
    rogue_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = mint_token(key=rogue_key)
    resp = await client.post(
        _GUARDED_PATH,
        json=_GUARDED_BODY,
        headers={"X-Internal-JWT": token},
    )
    assert resp.status_code == 401


async def test_expired_token_rejected_401(client, mint_token) -> None:
    """An otherwise-valid token whose exp is in the past → 401."""
    token = mint_token(exp_offset=-60)  # expired one minute ago
    resp = await client.post(
        _GUARDED_PATH,
        json=_GUARDED_BODY,
        headers={"X-Internal-JWT": token},
    )
    assert resp.status_code == 401


async def test_wrong_issuer_rejected_401(client, mint_token) -> None:
    """Correctly signed token with iss != worldview-gateway → 401 (F-015)."""
    token = mint_token(issuer="evil-issuer")
    resp = await client.post(
        _GUARDED_PATH,
        json=_GUARDED_BODY,
        headers={"X-Internal-JWT": token},
    )
    assert resp.status_code == 401


async def test_wrong_audience_rejected_401(client, mint_token) -> None:
    """Correctly signed token issued for a different audience → 401 (DEF-002).

    Prevents lateral movement: a token minted for service A must not be
    replayable at S8.
    """
    token = mint_token(audience="some-other-service")
    resp = await client.post(
        _GUARDED_PATH,
        json=_GUARDED_BODY,
        headers={"X-Internal-JWT": token},
    )
    assert resp.status_code == 401


async def test_missing_required_claims_rejected_401(client, rsa_key_pair) -> None:
    """A signed token missing required claims (no tenant_id/role) → 401.

    The middleware requires sub, tenant_id, role, exp, iss, aud. A token with
    only sub+iss+aud+exp must be rejected by the ``require`` option.
    """
    private_key, _ = rsa_key_pair
    token = _jwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000001",
            "iss": "worldview-gateway",
            "aud": "worldview-internal",
            "exp": int(time.time()) + 3600,
        },
        private_key,
        algorithm="RS256",
    )
    resp = await client.post(
        _GUARDED_PATH,
        json=_GUARDED_BODY,
        headers={"X-Internal-JWT": token},
    )
    assert resp.status_code == 401


async def test_skip_paths_bypass_the_boundary(unauth_client) -> None:
    """Health endpoints are exempt — no token required, never 401."""
    resp = await unauth_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.status_code != 401
