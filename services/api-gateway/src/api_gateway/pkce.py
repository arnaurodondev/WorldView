"""PKCE utilities and Valkey state management for the OIDC auth flow.

All functions are pure / stateless except for the Valkey helpers.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from messaging.valkey import ValkeyClient  # type: ignore[import-untyped]

_PKCE_KEY_PREFIX = "auth:pkce:"
_PKCE_TTL = 600  # 10 minutes


def generate_code_verifier() -> str:
    """Return a 43-char base64url-encoded code verifier (RFC 7636 §4.1).

    Uses ``secrets.token_urlsafe(32)`` which produces a 43-char URL-safe
    base64 string with no padding — exactly the PKCE spec minimum length.
    """
    return secrets.token_urlsafe(32)


def generate_code_challenge(code_verifier: str) -> str:
    """Return the S256 code challenge for *code_verifier* (RFC 7636 §4.2).

    ``BASE64URL(SHA256(ASCII(code_verifier)))`` — no padding characters.
    """
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def generate_state() -> str:
    """Return a 128-bit random nonce in UUID4 format for CSRF protection.

    Uses ``secrets.token_bytes`` directly to avoid stdlib ``uuid`` import guard.
    Version bits (4) and variant bits are set to produce a valid UUID4 string.
    """
    raw = bytearray(secrets.token_bytes(16))
    raw[6] = (raw[6] & 0x0F) | 0x40  # version 4
    raw[8] = (raw[8] & 0x3F) | 0x80  # RFC 4122 variant
    h = raw.hex()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


async def store_pkce_state(
    valkey: ValkeyClient | None,
    state: str,
    code_verifier: str,
    ttl: int = _PKCE_TTL,
) -> None:
    """Store ``auth:pkce:{state}`` → ``code_verifier`` in Valkey with *ttl* seconds.

    Raises ``RuntimeError("valkey_unavailable")`` if Valkey is None or raises
    an exception — login must fail closed (F-02, §9).
    """
    if valkey is None:
        raise RuntimeError("valkey_unavailable")
    try:
        await valkey.set(f"{_PKCE_KEY_PREFIX}{state}", code_verifier, ttl=ttl)
    except Exception as exc:
        raise RuntimeError("valkey_unavailable") from exc


async def retrieve_and_delete_pkce_state(
    valkey: ValkeyClient | None,
    state: str,
) -> str | None:
    """Atomically GET + DEL ``auth:pkce:{state}`` and return the code_verifier.

    Returns ``None`` if the key is missing or Valkey is unavailable.
    Uses a pipeline to minimise round-trips (GET + DEL in one call).
    """
    if valkey is None:
        return None
    key = f"{_PKCE_KEY_PREFIX}{state}"
    try:
        async with valkey.pipeline() as pipe:
            pipe.get(key)
            pipe.delete(key)
            results = await pipe.execute()
        code_verifier: str | None = results[0]
        return code_verifier
    except Exception:  # — fail-open: treat Valkey errors as cache miss
        return None
