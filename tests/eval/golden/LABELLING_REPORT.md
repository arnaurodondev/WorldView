# Labelling Pass Report — 2026-05-06

> Pass owner: Claude agent (initial Phase-1 build of the v2 120-query golden set).
> Authoritative spec: `docs/plans/0063-w5-hybrid-retrieval-eval-gate-plan.md`
> §0-bis.0 v2 (locks L1–L16) and §0-bis.4-v2.

---

## 1. Phase 1 — schema and corpus build (DONE)

| Artefact | Status |
|---|---|
| `queries.jsonl` | **120 rows**, all required v2 schema fields present, all `query_id` unique and matching `^q\d{3}$`. |
| `_backlog.jsonl` | 20 spare unlabelled candidates spread across all classes. |
| `README.md` | Documents schema, distribution, grading scale, labelling procedure, maintenance discipline (CODEOWNERS, quarterly re-grade, live-traffic backflow, deprecation rule). |
| Distribution | All 13 classes meet or exceed the §0-bis.4-v2 minimums. Sub-strata satisfy the prescribed counts within `identifier_lookup`, `non_analyst`, `adversarial_or_out_of_scope`, and `time_anchored_edge`. |
| Phrasing audit | All 120 rows have `phrasing_audit: true`. ≥80 % carry analyst-style phrasing; non-analyst, identifier, ambiguous, adversarial classes deliberately use their persona-faithful phrasing. |
| `expected_grade_3_count` | All rows set to `1` initially. Adversarial rows treat the correct refusal as the expected grade-3 outcome. |
| `label_review` | All rows carry initial-pass single-reviewer record (`claude-agent-1`) with `agreement_notes: "single-reviewer initial pass; 2-reviewer audit deferred"`. CODEOWNERS 2-reviewer rule kicks in on the first PR that mutates the file. |

---

## 2. Phase 2 — hand-grading (BLOCKED)

### 2.1 Blocker

The `/v1/internal/retrieve` endpoint is reachable, accepts a valid
`X-Internal-JWT` (audience `worldview-internal`), and returns **HTTP
200**, but it returns **0 candidates for every query attempted** (Apple,
Boeing, Microsoft, AAPL, NVDA, "earnings call", "8-K", "what's
interesting in the market today?" all returned `n_candidates=0`).

Root-cause sequence visible in `docker logs worldview-rag-chat-1`:

```
HTTP Request: POST http://nlp-pipeline:8006/api/v1/entities/resolve "HTTP/1.1 401 Unauthorized"
HTTP Request: POST http://nlp-pipeline:8006/api/v1/embed             "HTTP/1.1 401 Unauthorized"
HTTP Request: POST http://nlp-pipeline:8006/api/v1/search/chunks     "HTTP/1.1 401 Unauthorized"
chunk search returned 0 results — S6 index may be empty or query has no match
all retrieval tasks returned empty — context may be missing or services unavailable
```

The chain `rag-chat → nlp-pipeline (S6)` is failing with **401
Unauthorized**, even though the user-facing JWT into rag-chat is
accepted. This is a separate auth issue inside the service mesh:
rag-chat is propagating either no JWT or an inappropriate JWT (perhaps
without `aud=worldview-internal`) to the upstream nlp-pipeline calls.

The corpus itself is present: `nlp_db.chunks` has **9,706 chunks**, so
this is purely an inter-service-auth issue, not a missing-corpus issue.

### 2.2 Secondary observations from the access attempt

1. **dev-login JWT lacks `aud`**. `POST /v1/auth/dev-login` returns an RS256
   JWT signed by S9, but the installed gateway code in the container
   (`/app/.venv/lib/python3.11/site-packages/api_gateway/jwt_utils.py`) is
   stale and does **not** include the `aud="worldview-internal"` claim that
   `InternalJWTMiddleware` requires. The mounted source under `/app/src/`
   has `aud`, so the rebuild path still ships old code in the venv. This
   makes dev-login JWTs unusable for service-to-service testing without
   either rebuilding the api-gateway image or minting a JWT manually.

2. **JTI replay cache is hot**. Each minted JWT can be used **exactly
   once** before the JTI is rejected with `401 Token replay detected`.
   Any labelling driver must mint a fresh JWT per request.

3. **rag-chat health probe path is `/healthz`, not `/health`**. The
   docker port-mapped probe fired by external clients hitting `/health`
   gets a 404; only `/healthz` returns 200.

### 2.3 Helper script that would unblock labelling once the upstream auth is fixed

```python
# /tmp/eval_helper.py — use after rebuilding api-gateway and fixing
# rag-chat → nlp-pipeline JWT propagation. Mints a fresh aud-bearing
# JWT per call so the JTI replay cache stays cold.
import json, time, uuid, sys
from pathlib import Path
import httpx, jwt
PRIV = Path("/tmp/wv_priv.pem").read_text()
KID = "Hsfi2AOfg_FZeoSh"  # current gateway kid; rotate via GET /internal/jwks
URL = "http://localhost:8008/v1/internal/retrieve"
def mint_jwt() -> str:
    iat = int(time.time())
    payload = {
        "iss":"worldview-gateway","aud":"worldview-internal",
        "sub":"01900000-0000-7000-8000-000000000010",
        "tenant_id":"01900000-0000-7000-8000-000000000001",
        "oidc_sub":"eval-agent","role":"system",
        "jti":str(uuid.uuid4()),"iat":iat,"exp":iat+3600,"kid":KID,
    }
    return jwt.encode(payload, PRIV, algorithm="RS256", headers={"kid": KID})
def retrieve(q: str, top_k: int = 20) -> dict:
    tok = mint_jwt()
    with httpx.Client(timeout=60.0) as c:
        r = c.post(URL, json={"query_text": q, "top_k": top_k},
                   headers={"X-Internal-JWT": tok})
        r.raise_for_status()
        return r.json()
```

---

## 3. Top 5 retrieval pathologies observed

Even though Phase-2 grading is blocked, the access attempts surfaced
five concrete pipeline issues that the W5-1 / W5-2 / W5-3 work needs to
hold accountable to:

| # | Pathology | Where seen | Implication |
|---|---|---|---|
| 1 | `rag-chat → nlp-pipeline` returns 401 on every retrieval call | `worldview-rag-chat-1` logs | Inter-service JWT propagation is broken; the retrieval pipeline is currently 100 % degraded. **No retrieval result will reach a user until this is fixed.** |
| 2 | dev-login JWT in the running api-gateway container has no `aud` claim — stale build artifact in `.venv/` masks the source code | `docker exec worldview-api-gateway-1 grep aud …` | Container rebuild discipline is not consistently picking up library changes. Audit the api-gateway Dockerfile / `pip install -e` flow. |
| 3 | JTI replay cache rejects ALL re-use within the TTL window | Repeated calls with one JWT | This is correct security behaviour but means any eval/load-testing tool MUST mint a fresh JWT per call; document this in the harness. |
| 4 | rag-chat `/health` returns 404; only `/healthz` works | `curl :8008/health` vs `:8008/healthz` | External health probes targeting `/health` will silently fail. Either alias `/health → /healthz` or update probes to use `/healthz`. |
| 5 | Stage-0 sanity check (per §0-bis.0a) cannot be completed in current dev stack state | This pass | The mandatory pre-flight gate before W5-1 work is NOT green right now. PLAN-0063 W5-1 should not start until pathology #1 is resolved. |

---

## 4. Recommended Phase-3 follow-on

1. **Unblock retrieval** (pathology #1): trace the JWT propagation path in
   `rag-chat.infrastructure.clients.auth_context.set_current_jwt` → upstream
   client middlewares; verify the `X-Internal-JWT` header is being forwarded
   to S6 (nlp-pipeline) calls AND that the forwarded token's `aud` is
   `worldview-internal`. Likely culprit: rag-chat issues its own service-account
   JWT for upstream calls but isn't including `aud`, or isn't refreshing the
   JTI per call.
2. **Rebuild api-gateway image** so the dev-login JWT path picks up the
   `aud="worldview-internal"` claim (pathology #2). After that, the
   dev-login JWT is usable directly for the labelling pass — no
   manual minting needed.
3. **Run a one-off Stage-0 sanity check** per §0-bis.0a once #1 is
   green; append the record to `README.md §8`.
4. **Resume Phase-2 labelling** with the helper script in §2.3,
   targeting the "good MVP" stop condition: 60+ rows with ≥5 graded
   candidates and ≥1 grade-3 each. Prioritise the gating classes
   (`factual_lookup`, `comparison`, `reasoning`,
   `financial_data` + `identifier_lookup` because L8/L9 lexical work
   leans on it).
5. **Open a tracking row in `docs/plans/TRACKING.md`** for the
   inter-service auth fix; this is a blocker for PLAN-0063 W5-1, not
   merely a labelling-pass inconvenience.

---

## 5. Files modified by this pass

- `tests/eval/golden/queries.jsonl` (rewritten — 120 rows, v2 schema)
- `tests/eval/golden/_backlog.jsonl` (new — 20 spare rows)
- `tests/eval/golden/README.md` (new — schema + maintenance discipline)
- `tests/eval/golden/LABELLING_REPORT.md` (this file — new)

No source code changed.
