"""OIDC discovery and RSA key management utilities for the API Gateway."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC
from typing import Any

import httpx  # noqa: TCH002
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

from api_gateway.domain import OIDCProviderConfig

try:
    from common.time import utc_now  # type: ignore[import-untyped]
except ImportError:
    from datetime import datetime

    def utc_now() -> datetime:  # type: ignore[misc]
        return datetime.now(tz=UTC)


async def fetch_oidc_discovery(
    issuer_url: str,
    httpx_client: httpx.AsyncClient,
) -> OIDCProviderConfig:
    """Fetch OIDC discovery document and Zitadel public JWKS.

    Raises ``httpx.HTTPError`` or ``RuntimeError`` on failure.
    """
    discovery_url = f"{issuer_url.rstrip('/')}/.well-known/openid-configuration"
    resp = await httpx_client.get(discovery_url, timeout=10.0)
    resp.raise_for_status()
    doc: dict[str, Any] = resp.json()

    required = {"issuer", "authorization_endpoint", "token_endpoint", "end_session_endpoint", "jwks_uri"}
    missing = required - doc.keys()
    if missing:
        raise RuntimeError(f"OIDC discovery document missing fields: {missing}")

    # Fetch JWKS from Zitadel
    jwks_resp = await httpx_client.get(doc["jwks_uri"], timeout=10.0)
    jwks_resp.raise_for_status()
    jwks: dict[str, Any] = jwks_resp.json()

    public_keys = _parse_jwks(jwks)

    return OIDCProviderConfig(
        issuer=doc["issuer"],
        authorization_endpoint=doc["authorization_endpoint"],
        token_endpoint=doc["token_endpoint"],
        end_session_endpoint=doc["end_session_endpoint"],
        jwks_uri=doc["jwks_uri"],
        public_keys=public_keys,
        last_refreshed_at=utc_now(),
    )


async def refresh_oidc_jwks(
    config: OIDCProviderConfig,
    httpx_client: httpx.AsyncClient,
) -> OIDCProviderConfig | None:
    """Re-fetch JWKS from provider and return updated config. Returns None on failure."""
    try:
        jwks_resp = await httpx_client.get(config.jwks_uri, timeout=10.0)
        jwks_resp.raise_for_status()
        jwks: dict[str, Any] = jwks_resp.json()
        public_keys = _parse_jwks(jwks)
        return OIDCProviderConfig(
            issuer=config.issuer,
            authorization_endpoint=config.authorization_endpoint,
            token_endpoint=config.token_endpoint,
            end_session_endpoint=config.end_session_endpoint,
            jwks_uri=config.jwks_uri,
            public_keys=public_keys,
            last_refreshed_at=utc_now(),
        )
    except Exception:
        return None


def _parse_jwks(jwks: dict[str, Any]) -> dict[str, Any]:
    """Parse JWKS JSON into a kid → RSAPublicKey mapping."""
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

    keys: dict[str, Any] = {}
    for key_data in jwks.get("keys", []):
        if key_data.get("kty") != "RSA":
            continue
        kid = key_data.get("kid", "default")
        try:
            # Decode n and e from base64url
            n_bytes = base64.urlsafe_b64decode(_pad_b64(key_data["n"]))
            e_bytes = base64.urlsafe_b64decode(_pad_b64(key_data["e"]))
            n = int.from_bytes(n_bytes, "big")
            e = int.from_bytes(e_bytes, "big")
            public_key = RSAPublicNumbers(e, n).public_key(default_backend())
            keys[kid] = public_key
        except Exception:  # noqa: S112 — skip malformed JWK entries silently
            continue
    return keys


def _pad_b64(value: str) -> str:
    """Add base64url padding."""
    padding = 4 - len(value) % 4
    return value + "=" * (padding % 4)


def load_rsa_private_key(pem: str) -> RSAPrivateKey:
    """Load RSA private key from PEM string.

    Raises ``ValueError`` if the PEM is invalid or not an RSA key.
    """
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, RSAPrivateKey):
        raise ValueError("Provided key is not an RSA private key")
    return key


def rsa_key_id(public_key: RSAPublicKey) -> str:
    """Return a deterministic key ID (SHA-256 of DER-encoded public key, base64url, first 16 chars)."""
    der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    digest = hashlib.sha256(der).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")[:16]


def build_jwks_response(public_key: RSAPublicKey, kid: str) -> dict[str, Any]:
    """Build JWKS JSON for the internal RS256 public key.

    Returns ``{"keys": [{"kty":"RSA","alg":"RS256","use":"sig","kid":<kid>,"n":<modulus>,"e":"AQAB"}]}``.
    """
    if hasattr(public_key, "public_key"):
        pub_numbers = public_key.public_key().public_numbers()  # type: ignore[union-attr]
    else:
        pub_numbers = public_key.public_numbers()  # type: ignore[union-attr]
    n = pub_numbers.n
    e = pub_numbers.e

    def _int_to_b64url(value: int) -> str:
        byte_length = (value.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(value.to_bytes(byte_length, "big")).decode().rstrip("=")

    return {
        "keys": [
            {
                "kty": "RSA",
                "alg": "RS256",
                "use": "sig",
                "kid": kid,
                "n": _int_to_b64url(n),
                "e": _int_to_b64url(e),
            }
        ]
    }
