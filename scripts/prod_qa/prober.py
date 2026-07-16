"""In-pod API prober — the authenticated data-plane driver.

WHY IN-POD
----------
Prod runs real Zitadel OIDC and `/v1/auth/dev-login` is disabled, so the public
front door needs an interactive browser token we cannot get headlessly. Instead
we run a small prober INSIDE the api-gateway pod: it mints a short-lived internal
RS256 JWT with the gateway's OWN signer (`jwt_utils`) — byte-identical to the
`X-Internal-JWT` the gateway attaches when proxying downstream — and calls each
backend over ClusterIP. This exercises the real routes/processes/data through the
same trust path the gateway uses. (Layer-1 edge checks separately prove the
Zitadel gate is present and rejecting unauthenticated traffic.)

The whole prober runs as ONE `kubectl exec` and returns a single JSON blob that
every per-service API check reads from `Ctx.api`. Param shapes below were
captured live against prod on 2026-07-15 (e.g. ohlcv needs `from_date/to_date`,
quotes needs `instrument_ids`).
"""

from __future__ import annotations

import json

from . import harness as H

# The script executed inside the gateway pod. Kept as plain text (no f-string) so
# the backend code's own braces survive; the date window is templated at the top.
_PROBER = r"""
import json, os, urllib.request, urllib.error, datetime

from api_gateway.oidc import load_rsa_private_key
from api_gateway.jwt_utils import issue_user_jwt

_pem = os.environ.get("API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY")
_kid = os.environ.get("API_GATEWAY_JWT_KEY_VERSION", "v1")
if not _pem:
    from api_gateway.config import Settings
    _s = Settings(); _pem = _s.internal_jwt_private_key.get_secret_value(); _kid = _s.jwt_key_version
_pk = load_rsa_private_key(_pem)

def tok():
    # Fresh jti per call (backends enforce internal-JWT replay detection). Stable
    # synthetic UUID identity keeps reads deterministic.
    return issue_user_jwt(user_id="0195e2e0-0000-7000-8000-000000000001",
                          tenant_id="0195e2e0-0000-7000-8000-000000000002",
                          oidc_sub="prod-qa", private_key=_pk, kid=_kid, role="user")

R = {}
def call(name, url, method="GET", body=None, timeout=30):
    try:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
              headers={"X-Internal-JWT": tok(), "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(6000).decode("utf-8", "replace")
            R[name] = {"status": r.status, "len": len(raw), "body": raw}
    except urllib.error.HTTPError as e:
        R[name] = {"status": e.code, "len": 0, "body": e.read(600).decode("utf-8", "replace")}
    except Exception as e:
        R[name] = {"status": -1, "len": 0, "error": str(e)[:200]}

MD  = "http://market-data.worldview.svc:8003/api/v1"
KG  = "http://knowledge-graph.worldview.svc:8007/api/v1"
NLP = "http://nlp-pipeline.worldview.svc:8006/api/v1"
AL  = "http://alert.worldview.svc:8010/api/v1"
RC  = "http://rag-chat.worldview.svc:8008/api/v1"

today = datetime.date.today().isoformat()
frm   = (datetime.date.today() - datetime.timedelta(days=14)).isoformat()

# ── resolve the unified AAPL id (S3 instrument id == KG entity id, ADR-F-16) ──
call("md_lookup", MD + "/instruments/lookup?symbol=AAPL")
aid = None
try:
    aid = json.loads(R["md_lookup"]["body"]).get("id")
except Exception:
    pass
R["_aapl_id"] = {"status": 200, "body": aid or "", "len": len(aid or "")}

# ── market-data (S3) ─────────────────────────────────────────────────────────
call("md_ohlcv", MD + "/ohlcv/bars?symbol=AAPL&timeframe=1d&from_date=%s&to_date=%s" % (frm, today))
call("md_sector", MD + "/market/sector-returns?period=1D")
call("md_movers", MD + "/market/period-movers?period=1W&direction=gainers")
call("md_predlist", MD + "/prediction-markets?limit=3")
call("md_predcats", MD + "/prediction-markets/categories")
call("md_predevents", MD + "/prediction-markets/events?limit=3")
call("md_screen", MD + "/fundamentals/screen", "POST",
     {"filters": [{"field": "market_cap", "op": "gte", "value": 1e11}], "limit": 3})
if aid:
    call("md_quotes", MD + "/quotes/latest?instrument_ids=%s" % aid)
    call("md_fund_snap", MD + "/fundamentals/%s/snapshot" % aid)
    call("md_timeframes", MD + "/ohlcv/%s/timeframes" % aid)
# first prediction market → detail + history
try:
    mid = json.loads(R["md_predlist"]["body"])["items"][0]["market_id"]
    call("md_pred_detail", MD + "/prediction-markets/%s" % mid)
    call("md_pred_history", MD + "/prediction-markets/%s/history?interval=1h" % mid)
except Exception:
    pass

# ── knowledge-graph (S7) ─────────────────────────────────────────────────────
call("kg_stats", KG + "/graph/stats")
call("kg_lookup", KG + "/entities/lookup?ticker=AAPL")
call("kg_weird", KG + "/connections/weird?limit=5")
call("kg_temporal", KG + "/temporal-events?limit=5")
call("kg_similar", KG + "/entities/similar", "POST", {"entity_id": aid, "limit": 5} if aid else {"limit": 5})
if aid:
    call("kg_entity", KG + "/entities/%s" % aid)
    call("kg_intel", KG + "/entities/%s/intelligence" % aid)
    call("kg_graph", KG + "/entities/%s/graph" % aid)
    call("kg_predictions", KG + "/entities/%s/predictions" % aid)
    call("kg_refresh", KG + "/entities/%s/refresh" % aid, "POST", {})  # async description-gen trigger

# ── nlp-pipeline (S6) ────────────────────────────────────────────────────────
call("nlp_top", NLP + "/news/top?limit=5")
call("nlp_trend", NLP + "/news/trending-entities?window_hours=48&limit=5")
call("nlp_signals", NLP + "/signals?limit=5")
call("nlp_resolve", NLP + "/entities/resolve", "POST", {"query_text": "Apple"})
call("nlp_chunks", NLP + "/search/chunks", "POST", {"query_text": "Apple earnings revenue", "top_k": 5})
# synthetic embedding-worker E2E: long raw-Korean exercises the bge truncation +
# provider path the retry worker uses (pre-fix this 400'd on CJK under-count).
call("nlp_embed_cjk", NLP + "/embed", "POST",
     {"text": "미국 캘리포니아주 새너제이, 어떤 데이터 환경에서도 최적화된 성능을 제공하는 지능형 시스템입니다. " * 40})

# ── alert (S10) ──────────────────────────────────────────────────────────────
call("al_rules", AL + "/alert-rules")

# ── rag-chat (S8) golden Q (non-stream full generation can take 15-40s) ──────
call("chat", RC + "/chat", "POST",
     {"message": "What was AAPL's most recent closing price?"}, timeout=90)

print("PQA_JSON_START" + json.dumps(R) + "PQA_JSON_END")
"""


def run_prober(report: H.Report) -> tuple[dict, str]:
    """Execute the prober in the gateway pod. Returns (results, aapl_id)."""
    gw = H.gateway_pod()
    if not gw:
        report.fail("gateway", "in-pod prober", "no Running api-gateway pod found")
        return {}, ""
    cmd = f"kubectl -n {H.NS} exec -i {gw} -- python3 - <<'PYEOF'\n{_PROBER}\nPYEOF"
    _, out = H.sh(cmd, timeout=240)
    if "PQA_JSON_START" not in out:
        report.fail("gateway", "in-pod prober", f"prober did not return JSON: {out[-240:]}")
        return {}, ""
    try:
        blob = out.split("PQA_JSON_START", 1)[1].split("PQA_JSON_END", 1)[0]
        res = json.loads(blob)
    except (ValueError, IndexError) as e:
        report.fail("gateway", "in-pod prober", f"parse error: {e}")
        return {}, ""
    aid = (res.get("_aapl_id") or {}).get("body", "")
    report.ok("gateway", "in-pod prober", f"minted internal JWT, drove {len(res)} calls; AAPL id resolved={bool(aid)}")
    return res, aid
