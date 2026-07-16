"""Per-service prod-QA check modules.

Each module exposes `run(ctx: Ctx) -> None` and adds rows to `ctx.report`.
Shared helpers for reading the in-pod prober results live here.
"""

from __future__ import annotations

import json
from typing import Any

from ..harness import FAIL, PASS, WARN, Ctx


def api_json(ctx: Ctx, key: str) -> tuple[int, Any]:
    """Return (http_status, parsed-json-or-None) for a prober result key."""
    row = ctx.api_row(key)
    if not row:
        return 0, None
    status = row.get("status", 0)
    body = row.get("body", "")
    try:
        return status, json.loads(body) if isinstance(body, str) and body.strip().startswith(("{", "[")) else None
    except ValueError:
        return status, None


def assert_api_ok(
    ctx: Ctx,
    service: str,
    name: str,
    key: str,
    *,
    want_status: int = 200,
    min_len: int = 5,
    soft_on_missing: bool = True,
) -> tuple[bool, Any]:
    """Assert a probed endpoint returned `want_status` with a non-trivial body.

    Returns (ok, parsed_json). A not-probed key → WARN (endpoint may be gated by
    a missing upstream id) unless soft_on_missing=False.
    """
    row = ctx.api_row(key)
    if not row:
        ctx.report.add(service, name, WARN if soft_on_missing else FAIL, "not probed")
        return False, None
    status = row.get("status")
    if status != want_status:
        detail = f"HTTP {status} {row.get('error', '')} {str(row.get('body', ''))[:140]}"
        ctx.report.add(service, name, FAIL, detail)
        return False, None
    if row.get("len", 0) < min_len:
        ctx.report.add(service, name, WARN, f"HTTP {status} but body too small ({row.get('len')}B)")
        return False, None
    _, parsed = api_json(ctx, key)
    ctx.report.add(service, name, PASS, f"HTTP {status}, {row.get('len')}B")
    return True, parsed
