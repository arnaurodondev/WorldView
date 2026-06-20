"""Alert-rule CRUD composition functions for the API gateway (PLAN-0113).

S9 has no typed alert *client class* — ``clients.alert`` is a raw
``httpx.AsyncClient`` pointed at S10. These thin functions wrap the 5 CRUD
calls so the route layer stays declarative and the internal-JWT header plumbing
lives in one place. Each forwards the caller's verified auth headers (injected
internal JWT) so S10's InternalJWTMiddleware derives tenant_id/user_id from the
token (never from the body — PRD-0025).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

    from api_gateway.clients.base import ServiceClients

_BASE = "/api/v1/alert-rules"


async def create_rule(
    clients: ServiceClients,
    *,
    body: bytes,
    headers: dict[str, str],
) -> httpx.Response:
    """POST /api/v1/alert-rules → S10."""
    return await clients.alert.post(_BASE, content=body, headers={"Content-Type": "application/json", **headers})


async def list_rules(
    clients: ServiceClients,
    *,
    params: dict[str, str],
    headers: dict[str, str],
) -> httpx.Response:
    """GET /api/v1/alert-rules → S10 (query params forwarded verbatim)."""
    return await clients.alert.get(_BASE, params=params, headers=headers)


async def get_rule(
    clients: ServiceClients,
    *,
    rule_id: str,
    headers: dict[str, str],
) -> httpx.Response:
    """GET /api/v1/alert-rules/{rule_id} → S10."""
    return await clients.alert.get(f"{_BASE}/{rule_id}", headers=headers)


async def update_rule(
    clients: ServiceClients,
    *,
    rule_id: str,
    body: bytes,
    headers: dict[str, str],
) -> httpx.Response:
    """PATCH /api/v1/alert-rules/{rule_id} → S10."""
    return await clients.alert.patch(
        f"{_BASE}/{rule_id}", content=body, headers={"Content-Type": "application/json", **headers}
    )


async def delete_rule(
    clients: ServiceClients,
    *,
    rule_id: str,
    headers: dict[str, str],
) -> httpx.Response:
    """DELETE /api/v1/alert-rules/{rule_id} → S10."""
    return await clients.alert.delete(f"{_BASE}/{rule_id}", headers=headers)
