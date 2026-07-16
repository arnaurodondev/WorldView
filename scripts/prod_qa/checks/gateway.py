"""S9 api-gateway composition-route contracts + auth invariants (v4).

The gateway-S2S fix (fix/gateway-s2s-auth) made the gateway accept its own
internal JWT as a principal, restoring ~8 backend-composing routes that used to
401 for every service-to-service caller (chat tools, briefings, screener). The
prober drives those REAL ``/v1`` routes in-pod over ``localhost:8000`` (the same
app the edge serves), so this layer asserts:

* per-route CONTRACT — each composition route returns 200 + a non-empty, well-
  shaped payload (a regression that re-breaks the S2S trust path, drops the
  route prefix, or empties the compose leg is visible, not a silent ``[]``);
* AUTH invariants — a forged (wrong-key) and an expired internal JWT are both
  rejected (401), a ``role="system"`` service principal may READ but is denied a
  MUTATION by the least-privilege guard (401), and a real user keeps write
  authority (empty-body 422, never a 401 and never an actual mutation).

Everything here is read-only: the only writes attempted are two empty-body POSTs
that are designed to fail closed (401 by the guard / 422 by validation) BEFORE
any handler runs, so nothing is created.
"""

from __future__ import annotations

from .. import thresholds as T
from ..harness import Ctx
from . import api_json, assert_api_ok

SVC = "api-gateway"


def run(ctx: Ctx) -> None:
    _routes(ctx)
    _auth(ctx)


def _routes(ctx: Ctx) -> None:
    R = ctx.report

    # top-movers — S3 screener/period-movers composition.
    ok, body = assert_api_ok(ctx, SVC, "GW /market/top-movers", "gw_top_movers", min_len=T.GW_ROUTE_MIN_LEN)
    if ok and isinstance(body, dict):
        movers = body.get("movers") or body.get("results") or body.get("items") or []
        R.check(SVC, "top-movers returns a leaderboard", len(movers) > 0, f"{len(movers)} movers", soft=True)

    # screener POST — projection: results carry the flattened top-level fields.
    ok, body = assert_api_ok(ctx, SVC, "GW /fundamentals/screen (POST projection)", "gw_screen",
                             min_len=T.GW_ROUTE_MIN_LEN)
    if ok and isinstance(body, dict):
        results = body.get("results") or []
        first = results[0] if results else {}
        projected = [k for k in ("ticker", "name", "market_cap", "gics_sector") if k in first]
        R.check(
            SVC,
            "screener projection flattens metric fields",
            len(results) > 0 and len(projected) >= 3,
            f"{len(results)} results; projected={projected}",
        )

    # economic calendar — S7 temporal-events (macro) proxy → {events:[...]}.
    ok, body = assert_api_ok(ctx, SVC, "GW /fundamentals/economic-calendar", "gw_econ_cal",
                             min_len=T.GW_ROUTE_MIN_LEN)
    if ok and isinstance(body, dict):
        events = body.get("events") or []
        R.check(SVC, "economic-calendar returns macro events", len(events) > 0, f"{len(events)} events", soft=True)

    # entity intelligence — S7 composed narrative + health.
    ok, body = assert_api_ok(ctx, SVC, "GW /entities/{id}/intelligence", "gw_intel", min_len=T.GW_ROUTE_MIN_LEN)
    if ok and isinstance(body, dict):
        R.check(
            SVC,
            "entity intelligence shaped (name+health_score)",
            T.KG_GOLDEN_NAME_SUBSTR.lower() in str(body.get("canonical_name", "")).lower()
            and isinstance(body.get("health_score"), (int, float)),
            f"name={body.get('canonical_name')} health={body.get('health_score')}",
        )

    # pairwise pathfinding — deterministic shape (connected flag + paths list).
    ok, body = assert_api_ok(ctx, SVC, "GW /paths/between", "gw_paths", min_len=T.GW_ROUTE_MIN_LEN)
    if ok and isinstance(body, dict):
        R.check(
            SVC,
            "paths/between well-formed (connected+paths)",
            "connected" in body and isinstance(body.get("paths"), list),
            f"connected={body.get('connected')} paths={len(body.get('paths') or [])}",
        )

    # alerts pending — S10 proxy (empty list is valid for the synthetic user).
    st, _ = api_json(ctx, "gw_alerts_pending")
    R.check(SVC, "GW /alerts/pending route up", st == 200, f"HTTP {st}")

    # morning brief — S8 composition (may 503 on cold generation → soft).
    row = ctx.api_row("gw_brief")
    if row:
        s = row.get("status")
        R.check(SVC, "GW /briefings/morning composed", s == 200, f"HTTP {s}", soft=(s == 503))


def _auth(ctx: Ctx) -> None:
    R = ctx.report

    def status(key: str) -> int:
        return int((ctx.api_row(key) or {}).get("status", 0))

    # Negative: a forged (wrong-key) internal JWT must be rejected — the gateway
    # verifies RS256 against its own public key, so a token minted with any other
    # key cannot pass and the route emits its normal 401.
    R.check(SVC, "forged internal JWT rejected (401)", status("auth_forged") == 401, f"HTTP {status('auth_forged')}")

    # Negative: an expired internal JWT (valid signer, exp in the past) is rejected.
    R.check(SVC, "expired internal JWT rejected (401)", status("auth_expired") == 401,
            f"HTTP {status('auth_expired')}")

    # Positive: a role=system service principal may READ (S2S composition path).
    sr = status("auth_system_read")
    R.check(SVC, "system principal may read (not 401)", sr not in (401, 403, 0), f"HTTP {sr}")

    # Negative: the S2S least-privilege guard denies a system principal on a
    # MUTATION route (POST /v1/alerts) → 401 (user stays None).
    R.check(SVC, "system principal mutation denied (401)", status("auth_system_mutation") == 401,
            f"HTTP {status('auth_system_mutation')}")

    # Positive: a real user keeps write authority on the same route — the guard is
    # system-specific. Empty body fails validation (422) BEFORE any write, so this
    # proves the user auth path works without ever mutating.
    um = status("auth_user_mutation")
    R.check(SVC, "real-user mutation path works (422, not 401)", um == 422,
            f"HTTP {um} (422 = passed auth, failed validation — no mutation)")
