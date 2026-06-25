"""E2E fixtures for rag-chat (S8) — real internal-JWT security boundary.

These fixtures build the production app via ``create_app`` with
``internal_jwt_skip_verification=False`` (fail-closed) and inject a real RS256
public key onto ``app.state`` so ``InternalJWTMiddleware`` runs its *real*
signature/issuer/audience/claims validation — exactly the boundary that the
mocked unit/integration tiers bypass (the audit notes the conftest there
decodes with ``verify_signature=False``).

No external infrastructure is required: the app is driven in-process via
``httpx.ASGITransport`` and the JWKS HTTP fetch is short-circuited by setting
``app.state._internal_jwt_public_key`` directly (the same hook the middleware
reads first, see ``internal_jwt.py`` ``dispatch``). The lifespan is therefore
NOT entered — these tests exercise the middleware + route wiring only, and
stub any ``app.state`` use case the route reaches.
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

# The boot guard (assert_app_env_or_die) requires APP_ENV when skip_verification
# is True. We use skip_verification=False here, but pin APP_ENV before any
# settings import for parity with the rest of the suite.
os.environ.setdefault("APP_ENV", "test")

import jwt as _jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from rag_chat.app import create_app
from rag_chat.infrastructure.config.settings import RagChatSettings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# Issuer/audience the middleware validates against (observability defaults).
_ISSUER = "worldview-gateway"
_AUDIENCE = "worldview-internal"


@pytest.fixture(autouse=True)
def _reset_sse_starlette_app_status() -> None:
    """Reset sse_starlette AppStatus.should_exit_event before each test (BP-435)."""
    try:
        from sse_starlette.sse import AppStatus

        AppStatus.should_exit_event = None
        AppStatus.should_exit = False
    except ImportError:
        pass


@pytest.fixture(scope="session")
def rsa_key_pair():
    """A single RSA key pair shared across the session — we control both sides."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture
def settings() -> RagChatSettings:
    """Fail-closed settings: skip_verification=False → REAL RS256 validation."""
    return RagChatSettings(
        database_url="postgresql+asyncpg://fake:fake@localhost:5432/fake_rag_db",
        s1_internal_token="test-token",
        log_json=False,
        log_level="WARNING",
        internal_jwt_skip_verification=False,
    )


@pytest.fixture
def app(settings: RagChatSettings, rsa_key_pair):  # type: ignore[no-untyped-def]
    """Production app with a real public key injected (no JWKS HTTP fetch, no lifespan)."""
    _private, public_key = rsa_key_pair
    application = create_app(settings)
    # The middleware reads ``app.state._internal_jwt_public_key`` first; setting it
    # makes the real verification path run without a live S9 / JWKS endpoint.
    application.state._internal_jwt_public_key = public_key
    return application


@pytest.fixture
def mint_token(rsa_key_pair):  # type: ignore[no-untyped-def]
    """Return a helper that mints RS256 internal JWTs signed with the test key.

    Defaults produce a fully valid token; override kwargs to craft rejection cases.
    """
    private_key, _public = rsa_key_pair

    def _mint(
        *,
        sub: str = "00000000-0000-0000-0000-000000000001",
        tenant_id: str = "00000000-0000-0000-0000-000000000002",
        role: str = "user",
        issuer: str = _ISSUER,
        audience: str = _AUDIENCE,
        exp_offset: int = 3600,
        algorithm: str = "RS256",
        key=None,
        extra: dict | None = None,
    ) -> str:
        claims = {
            "sub": sub,
            "tenant_id": tenant_id,
            "role": role,
            "iss": issuer,
            "aud": audience,
            "exp": int(time.time()) + exp_offset,
            "iat": int(time.time()),
        }
        if extra:
            claims.update(extra)
        signing_key = key if key is not None else private_key
        return _jwt.encode(claims, signing_key, algorithm=algorithm)

    return _mint


@pytest.fixture
async def unauth_client(app) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    """Client with NO X-Internal-JWT header."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    """Client without default auth — tests attach per-request headers explicitly."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
