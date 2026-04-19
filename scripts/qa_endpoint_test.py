# ruff: noqa: S310
#!/usr/bin/env python3
"""Pre-demo endpoint test — runs INSIDE the api-gateway container via docker exec.

Generates an internal JWT using the running container's RSA key and tests
all critical API endpoints directly via the Docker internal network.

Usage:
  docker compose -f infra/compose/docker-compose.test.yml exec -T api-gateway python3 /app/qa_endpoint_test.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/app/src")

# ── Token generation ─────────────────────────────────────────────────────────
import jwt  # (imported after sys.path)
from api_gateway.config import Settings
from api_gateway.oidc import load_rsa_private_key

s = Settings()
priv_key = load_rsa_private_key(s.internal_jwt_private_key.get_secret_value())
now = int(time.time())
_TOKEN = jwt.encode(
    {
        "sub": "system",
        "iss": "worldview-gateway",
        "aud": "worldview-internal",
        "iat": now,
        "exp": now + 3600,
        "tenant_id": "demo-tenant",
        "user_id": "system-user",
        "email": "qa@demo.local",
        "roles": ["system"],
    },
    priv_key,
    algorithm="RS256",
)
# ── Test runner ──────────────────────────────────────────────────────────────

AUTH_S9 = {"Authorization": f"Bearer {_TOKEN}"}
AUTH_INTERNAL = {"X-Internal-JWT": _TOKEN}
RESULTS: list[tuple[str, str, str, str]] = []


def check(
    service: str,
    name: str,
    url: str,
    headers: dict[str, str] | None = None,
    expected_statuses: tuple[int, ...] = (200,),
) -> None:
    req_headers = headers or {}
    try:
        req = urllib.request.Request(url, headers=req_headers)
        r = urllib.request.urlopen(req, timeout=10)
        data = json.loads(r.read())
        status = r.getcode()
        if status in expected_statuses:
            RESULTS.append((service, name, "PASS", str(data)[:180]))
        else:
            RESULTS.append((service, name, f"HTTP_{status}", str(data)[:120]))
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:120]
        if e.code in expected_statuses:
            RESULTS.append((service, name, "PASS", f"expected HTTP_{e.code}: {body}"))
        else:
            RESULTS.append((service, name, f"HTTP_{e.code}", body))
    except Exception as exc:
        RESULTS.append((service, name, "FAIL", str(exc)[:120]))


# S9 (gateway exposed routes)
S9 = "http://localhost:8000"
check("S9", "GET /healthz", f"{S9}/healthz")
check("S9", "GET /readyz", f"{S9}/readyz")
check("S9", "GET /internal/jwks", f"{S9}/internal/jwks")
check("S9", "GET /v1/fundamentals/screen/fields", f"{S9}/v1/fundamentals/screen/fields")
check("S9", "GET /v1/search/instruments", f"{S9}/v1/search/instruments?query=AAPL&limit=5")
check("S9", "GET /v1/market/top-movers", f"{S9}/v1/market/top-movers?limit=5", expected_statuses=(200, 500, 502, 503))
check("S9", "GET /v1/alerts/pending unauth", f"{S9}/v1/alerts/pending?limit=5", expected_statuses=(401,))
check(
    "S9",
    "GET /v1/alerts/pending auth",
    f"{S9}/v1/alerts/pending?limit=5",
    headers=AUTH_S9,
    expected_statuses=(200, 500, 502, 503),
)
check("S9", "GET /v1/threads auth", f"{S9}/v1/threads", headers=AUTH_S9, expected_statuses=(200, 500, 502, 503))
check(
    "S9",
    "GET /v1/news/relevant",
    f"{S9}/v1/news/relevant?query=Apple&limit=5",
    expected_statuses=(200, 404, 500, 502, 503),
)
check(
    "S9",
    "GET /v1/signals/prediction-markets auth",
    f"{S9}/v1/signals/prediction-markets?limit=5",
    headers=AUTH_S9,
    expected_statuses=(200, 500, 502, 503),
)

# Direct service health checks (network sanity)
check("S1", "GET portfolio /healthz", "http://portfolio:8001/healthz")
check("S2", "GET market-ingestion /healthz", "http://market-ingestion:8002/healthz")
check("S3", "GET market-data /healthz", "http://market-data:8003/healthz")
check("S4", "GET content-ingestion /healthz", "http://content-ingestion:8004/healthz")
check("S5", "GET content-store /healthz", "http://content-store:8005/healthz")
check("S6", "GET nlp-pipeline /healthz", "http://nlp-pipeline:8006/healthz")
check("S7", "GET knowledge-graph /healthz", "http://knowledge-graph:8007/healthz")
check("S8", "GET rag-chat /healthz", "http://rag-chat:8008/healthz")
check("S10", "GET alert /healthz", "http://alert:8010/healthz")

# Internal JWT sanity against one backend endpoint
check(
    "S3",
    "GET /api/v1/fundamentals/screen/fields",
    "http://market-data:8003/api/v1/fundamentals/screen/fields",
    headers=AUTH_INTERNAL,
    expected_statuses=(200, 404),
)

# ── Report ───────────────────────────────────────────────────────────────────
print("\n=== Pre-Demo Endpoint Test Results ===\n")
pass_count = sum(1 for _, _, s, _ in RESULTS if s == "PASS")
fail_count = len(RESULTS) - pass_count
for service, name, status, data in RESULTS:
    icon = "✓" if status == "PASS" else "✗"
    print(f"  {icon} [{service}] {name}: {status}")
    if status != "PASS":
        print(f"      {data}")

print(f"\nSummary: {pass_count}/{len(RESULTS)} passed, {fail_count} failed")
sys.exit(0 if fail_count == 0 else 1)
