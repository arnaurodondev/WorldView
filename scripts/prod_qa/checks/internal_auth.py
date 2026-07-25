"""Cross-service internal-JWT signer health (independent-signer auth class).

WHY THIS EXISTS
---------------
2026-07-23 incident: ``market-ingestion-scheduler`` and ``portfolio-snapshot-
worker`` got 100% 401 responses on EVERY call they made to market-data for
24+ hours. Each service mints its OWN ``X-Internal-JWT`` directly (via the
shared ``observability.internal_jwt.mint_internal_jwt`` helper) — this is a
DIFFERENT trust path from api-gateway's signer, which is the ONLY one the
existing LAYER 2 / gateway in-pod prober (``scripts/prod_e2e_smoke.py``,
``scripts/prod_qa/prober.py``) exercises. api-gateway's own signing stayed
perfectly healthy the entire time, so a gateway-only auth check structurally
cannot see this bug class: it proves ONE signer works, not ALL of them.

The failure was also invisible to every other existing guard:
  * the coarse "internal-JWT signing keys non-empty" scan
    (``checks/coarse.py::_internal_jwt_signing_keys``) only flags a key env
    var that IS SET but shorter than a real PEM — it says nothing when the
    var is entirely ABSENT from the pod's env (which is what actually
    happened here; see the module docstring in ``thresholds.py`` next to
    ``INTERNAL_AUTH_PROBES``), and it never actually calls the target, so it
    cannot catch a MISMATCHED key pair (present, well-formed, wrong keypair)
    either — only this module's live functional call can.
  * each service's own error handling swallows the 401 and falls back to
    degraded behaviour (stale prices, cost-basis valuation) rather than
    crashing or alerting — by design, this is silent from inside the service.

This check closes that whole class, generically: for every KNOWN caller→
target relationship in ``T.INTERNAL_AUTH_PROBES``, it reproduces the EXACT
mint call the real production code path makes (same ``sub``, same HS256
dev-fallback secret literal, same target base-URL env var/default) INSIDE the
caller's own pod — so it uses the caller's REAL env, not a stand-in — and
calls a cheap, safe, read-only endpoint on the target service. A future
signer added to that list is covered the day it ships; the driver here never
needs to change.

Read-only: every target endpoint is a GET a real caller already makes in
production (an instrument list-page / lookup), never a mutation.
"""

from __future__ import annotations

from .. import harness as H
from .. import thresholds as T
from ..harness import Ctx

SVC = "internal-auth"

# The prober script executed inside the CALLER's own pod via `kubectl exec`.
# Kept parameterised (not an f-string) so the caller's real env is read live,
# not baked in at harness-build time. `{key_env_var}` etc. are substituted with
# literal python identifiers/strings via .format() below — none of them are
# attacker-controlled (they all come from the INTERNAL_AUTH_PROBES constant).
_PROBE_TEMPLATE = """
import os, urllib.request, urllib.error
from observability.internal_jwt import mint_internal_jwt

pem = os.environ.get({key_env_var!r}, "")
base = os.environ.get({target_env_var!r}, {target_default!r}).rstrip("/")
tok = mint_internal_jwt(
    sub={sub!r},
    ttl_seconds=120,
    private_key_pem=pem,
    dev_hs256_secret={dev_secret!r},
)
url = base + {path!r}
req = urllib.request.Request(url, method="GET", headers={{"X-Internal-JWT": tok}})
try:
    r = urllib.request.urlopen(req, timeout=15)
    print("PQA_IA", r.status, bool(pem))
except urllib.error.HTTPError as e:
    print("PQA_IA", e.code, bool(pem), e.read(200).decode("utf-8", "replace"))
except Exception as e:
    print("PQA_IA", -1, bool(pem), type(e).__name__, str(e)[:200])
"""


def run(ctx: Ctx) -> None:
    for probe in T.INTERNAL_AUTH_PROBES:
        _run_probe(ctx, probe)


def _run_probe(ctx: Ctx, probe: dict[str, str]) -> None:
    R = ctx.report
    name = probe["name"]
    pod = H.running_pod(probe["caller_label"])
    if not pod:
        R.warn(SVC, name, f"no Running pod for label {probe['caller_label']}")
        return

    script = _PROBE_TEMPLATE.format(
        key_env_var=probe["key_env_var"],
        target_env_var=probe["target_env_var"],
        target_default=probe["target_default"],
        sub=probe["sub"],
        dev_secret=probe["dev_secret"],
        path=probe["path"],
    )
    cmd = f"kubectl -n {H.NS} exec -i {pod} -- python3 - <<'PYEOF'\n{script}\nPYEOF"
    _, out = H.sh(cmd, timeout=45)
    line = next((ln for ln in out.splitlines() if ln.startswith("PQA_IA")), "")
    parts = line.split(maxsplit=3)
    status = H.as_int(parts[1], -999) if len(parts) >= 2 else -999
    key_present = parts[2] if len(parts) >= 3 else "?"
    extra = parts[3] if len(parts) >= 4 else ""

    if status == 200:
        R.ok(SVC, name, f"HTTP 200 (own signing key present={key_present})")
    elif status in (401, 403):
        R.fail(
            SVC,
            name,
            f"HTTP {status} — this signer's own internal-JWT is REJECTED by the target "
            f"(own key present={key_present}); every real call on this path is failing "
            f"silently the same way {extra}".strip(),
        )
    else:
        R.warn(SVC, name, f"probe inconclusive: {line[:160] or out[-160:]}")
