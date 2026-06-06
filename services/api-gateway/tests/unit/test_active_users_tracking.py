"""Unit tests for PLAN-0094 W1 / T-W1-03 — active_users ZADD on successful auth.

Wave W1 of PLAN-0094 has ``OIDCAuthMiddleware`` write to a global Valkey
sorted-set ``active_users`` (member = user_id, score = unix-seconds) on
every successful JWT decode. Wave W2 will read that set to decide which
users have been active in the eligibility window for the daily-brief
worker, so we need three behavioural guarantees pinned right now:

    1. After a successful auth, ``valkey.zadd("active_users", {<id>: <ts>})``
       was actually called.
    2. A Valkey failure during that ZADD must NOT 503 a successful auth —
       the auth path is hot and best-effort tracking can't break it.
    3. The failure case must emit a structured warning so operators can
       spot a degraded ZADD (silent failures = silent regressions, see
       MEMORY: "Audit return values must be persisted").

The dev-mode internal-JWT branch is the easiest exercise: we issue a
short-lived gateway-style JWT with ``rs256`` against the test keypair and
let ``OIDCAuthMiddleware`` validate it in the no-OIDC path (``app.state
.oidc_config = None``). That branch sets ``request.state.user`` and calls
``_record_active_user`` with the user_id — exactly the production code
path we care about.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import jwt as pyjwt
import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit


# ── Helpers ────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def rsa_keypair():
    """Module-scoped RSA-2048 keypair — generation is expensive (~100ms)."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    return private_key, private_key.public_key()


def _make_app() -> FastAPI:
    """Trivial app with a single ``/probe`` route used by every test below."""
    app = FastAPI()

    @app.get("/probe")
    async def probe() -> dict[str, bool]:
        return {"ok": True}

    return app


def _build_internal_jwt(private_key, *, user_id: str = "u-active-1") -> str:
    """Mint a gateway-issued internal JWT the dev-mode branch will accept.

    The audience MUST be ``worldview-internal`` and ``iss`` must be
    ``worldview-gateway`` — those are the two assertions the dev-mode path
    enforces before populating ``request.state.user``.
    """
    now = int(time.time())
    payload = {
        "iss": "worldview-gateway",
        "sub": user_id,  # used as user_id when no Valkey cache hit
        "aud": "worldview-internal",
        "exp": now + 300,
        "iat": now,
        "tenant_id": "t-1",
        "role": "user",
    }
    return pyjwt.encode(payload, private_key, algorithm="RS256")


def _make_valkey_mock(*, zadd_raises: BaseException | None = None) -> AsyncMock:
    """Build a Valkey AsyncMock for the auth path.

    - ``get(auth:user:*)``     → None (force the token-claims fall-back path).
    - ``zadd(active_users)``   → succeeds, unless ``zadd_raises`` is set.
    - ``zremrangebyscore``     → no-op (rarely fired due to probabilistic prune).
    """
    valkey = AsyncMock()
    valkey.get = AsyncMock(return_value=None)
    if zadd_raises is not None:
        valkey.zadd = AsyncMock(side_effect=zadd_raises)
    else:
        valkey.zadd = AsyncMock(return_value=1)
    valkey.zremrangebyscore = AsyncMock(return_value=0)
    return valkey


def _wire_app(app: FastAPI, valkey, public_key) -> None:
    """Wire app.state for the dev-mode internal-JWT branch.

    ``oidc_config = None`` switches OIDCAuthMiddleware into the dev branch,
    where it validates Bearer tokens with ``app.state.rsa_public_key``.
    """
    from api_gateway.middleware import OIDCAuthMiddleware

    app.state.oidc_config = None
    app.state.valkey = valkey
    app.state.rsa_public_key = public_key
    app.add_middleware(OIDCAuthMiddleware)


# ── T-W1-03 tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_jwt_auth_writes_active_users_zadd(rsa_keypair) -> None:
    """T-W1-03: a successful auth calls ``valkey.zadd("active_users", {id: ts})``.

    We assert on the call args: the key must be exactly ``active_users``
    (the contract Wave W2 will read against) and the dict must contain the
    JWT subject as the member with a recent unix-seconds score.
    """
    private_key, public_key = rsa_keypair
    token = _build_internal_jwt(private_key, user_id="u-active-1")
    valkey = _make_valkey_mock()

    app = _make_app()
    _wire_app(app, valkey, public_key)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/probe", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200, "auth should succeed (dev-mode internal JWT path)"
    # Exactly one ZADD against the canonical key. More than one would mean
    # both OIDCAuthMiddleware branches fired (a bug); zero would mean the
    # helper is gated incorrectly and the daily-brief worker would never
    # see this user (silent regression of the W2 contract).
    assert valkey.zadd.await_count == 1, f"expected 1 zadd call, got {valkey.zadd.await_count}"
    call_args = valkey.zadd.await_args
    assert call_args is not None
    assert call_args.args[0] == "active_users", f"expected key 'active_users', got {call_args.args[0]!r}"
    mapping = call_args.args[1]
    assert "u-active-1" in mapping, f"expected user_id in zadd mapping, got {mapping!r}"
    # Score must be a recent unix-seconds timestamp; allow ±5s for clock skew.
    score = mapping["u-active-1"]
    now = int(time.time())
    assert abs(score - now) <= 5, f"expected score near now ({now}), got {score}"


@pytest.mark.asyncio
async def test_jwt_auth_valkey_failure_does_not_503(rsa_keypair) -> None:
    """T-W1-03: when ``valkey.zadd`` raises, the auth path still returns 200.

    Best-effort tracking — a Valkey hiccup must NEVER 503 a user who would
    otherwise have been authenticated. This is the single most important
    invariant of the W1 helper.
    """
    private_key, public_key = rsa_keypair
    token = _build_internal_jwt(private_key, user_id="u-active-2")
    # Simulate a hard Valkey failure on the ZADD specifically. ``get`` still
    # works fine — only the tracking write blows up. This isolates the helper
    # error path from a wholesale Valkey outage (which is covered separately
    # in test_rate_limit_middleware_resilience.py).
    valkey = _make_valkey_mock(zadd_raises=ConnectionError("valkey down"))

    app = _make_app()
    _wire_app(app, valkey, public_key)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/probe", headers={"Authorization": f"Bearer {token}"})

    # The bedrock invariant: the auth path must NOT propagate a Valkey
    # tracking error to the user. Any other status here is a regression of
    # the best-effort contract.
    assert resp.status_code == 200, f"valkey zadd failure must not block auth — got {resp.status_code}"


@pytest.mark.asyncio
async def test_jwt_auth_records_warning_on_valkey_failure(rsa_keypair) -> None:
    """T-W1-03: a Valkey failure emits the structured ``active_users_zadd_failed`` warning.

    The warning is the audit trail Wave W2 will rely on when chasing missing
    eligibility entries. We patch the module-level structlog logger and
    inspect the warning calls; the event name MUST be exactly
    ``active_users_zadd_failed`` (operators grep on it). The exception class
    name MUST be included so degraded modes are distinguishable in logs.
    """
    private_key, public_key = rsa_keypair
    token = _build_internal_jwt(private_key, user_id="u-active-3")
    valkey = _make_valkey_mock(zadd_raises=ConnectionError("valkey reset"))

    app = _make_app()
    _wire_app(app, valkey, public_key)

    import api_gateway.middleware as _mw

    with patch.object(_mw, "logger") as mock_logger:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/probe", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    # Find the warning calls whose first positional arg is the expected event name.
    warning_calls = [
        c for c in mock_logger.warning.call_args_list if c.args and c.args[0] == "active_users_zadd_failed"
    ]
    assert warning_calls, (
        "T-W1-03: a Valkey zadd failure must log 'active_users_zadd_failed' — "
        f"observed warning calls: {[c.args for c in mock_logger.warning.call_args_list]}"
    )
    # Verify the kwargs carry the error_type so degraded modes are distinguishable.
    call_kwargs = warning_calls[0].kwargs
    assert (
        call_kwargs.get("error_type") == "ConnectionError"
    ), f"expected error_type=ConnectionError, got {call_kwargs.get('error_type')!r}"
