# ruff: noqa: S310
#!/usr/bin/env python3
"""Exhaustive QA test script for the Worldview platform.

Runs OUTSIDE Docker containers against the live dev stack:
  - S9 API Gateway at http://localhost:8000
  - Frontend at http://localhost:3001

Authenticates via POST /v1/auth/dev-login and tests auth boundaries,
endpoint coverage, response schemas, security, frontend smoke, and
infrastructure health.

Usage:
    python3 scripts/qa_exhaustive.py

Exit codes:
    0 — all tests passed (expected failures do not count)
    1 — one or more unexpected failures
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

S9_BASE = "http://localhost:8000"
FRONTEND_BASE = "http://localhost:3001"
REQUEST_TIMEOUT = 5  # seconds per request

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

# Each result: (category, name, status, detail)
# status is one of: "PASS", "FAIL", "EXPECTED_FAIL"
RESULTS: list[tuple[str, str, str, str]] = []


def record(category: str, name: str, passed: bool, detail: str = "", expected_fail: str | None = None) -> None:
    """Record a single test result."""
    if passed:
        RESULTS.append((category, name, "PASS", detail))
    elif expected_fail:
        RESULTS.append((category, name, "EXPECTED_FAIL", f"[{expected_fail}] {detail}"))
    else:
        RESULTS.append((category, name, "FAIL", detail))


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only)
# ---------------------------------------------------------------------------


def http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: int = REQUEST_TIMEOUT,
) -> tuple[int, dict[str, str], bytes]:
    """Make an HTTP request, return (status_code, response_headers, body_bytes).

    Handles HTTPError so the caller always gets a status code back.
    Raises ConnectionError (or similar) if the service is unreachable.
    """
    req_headers = headers or {}
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode()
        req_headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        resp_headers = {k.lower(): v for k, v in resp.getheaders()}
        return resp.getcode(), resp_headers, resp.read()
    except urllib.error.HTTPError as e:
        resp_headers = {k.lower(): v for k, v in e.headers.items()}
        return e.code, resp_headers, e.read()


def http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: int = REQUEST_TIMEOUT,
) -> tuple[int, dict[str, str], Any]:
    """Like http_request but parses body as JSON.  Returns raw bytes on parse failure."""
    status, resp_headers, raw = http_request(url, method=method, headers=headers, body=body, timeout=timeout)
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        parsed = raw
    return status, resp_headers, parsed


# ---------------------------------------------------------------------------
# Auth helper — obtain a dev-login token
# ---------------------------------------------------------------------------


def obtain_dev_token() -> str | None:
    """POST /v1/auth/dev-login and return the access_token, or None on failure."""
    try:
        status, _, data = http_json(f"{S9_BASE}/v1/auth/dev-login", method="POST")
        if status == 200 and isinstance(data, dict) and "access_token" in data:
            return data["access_token"]
        print(f"  [WARN] dev-login returned {status}: {str(data)[:200]}")
        return None
    except Exception as exc:
        print(f"  [ERROR] Could not reach S9 for dev-login: {exc}")
        return None


# ---------------------------------------------------------------------------
# Connectivity pre-check
# ---------------------------------------------------------------------------


def check_connectivity() -> bool:
    """Verify S9 is reachable before running tests."""
    try:
        status, _, _ = http_request(f"{S9_BASE}/healthz", timeout=3)
        return status == 200
    except Exception:
        return False


# ===================================================================
# Category 1: Auth Boundary Tests (10 tests)
# ===================================================================


def run_auth_boundary_tests(token: str) -> None:
    cat = "Auth Boundary Tests"
    auth_hdr = {"Authorization": f"Bearer {token}"}

    # 1. POST /v1/auth/dev-login -> 200 with expected fields
    try:
        status, _, data = http_json(f"{S9_BASE}/v1/auth/dev-login", method="POST")
        has_fields = (
            isinstance(data, dict)
            and "access_token" in data
            and "user" in data
            and "token_type" in data
            and "expires_in" in data
        )
        record(
            cat,
            "POST /v1/auth/dev-login -> 200 with fields",
            status == 200 and has_fields,
            f"status={status}, has_fields={has_fields}",
        )
    except Exception as exc:
        record(cat, "POST /v1/auth/dev-login -> 200 with fields", False, str(exc))

    # 2. GET /v1/auth/ws-token with valid auth -> 200
    try:
        status, _, _ = http_json(f"{S9_BASE}/v1/auth/ws-token", headers=auth_hdr)
        record(cat, "GET /v1/auth/ws-token authed -> 200", status == 200, f"status={status}")
    except Exception as exc:
        record(cat, "GET /v1/auth/ws-token authed -> 200", False, str(exc))

    # 3. GET /v1/auth/ws-token without auth -> 401
    try:
        status, _, _ = http_json(f"{S9_BASE}/v1/auth/ws-token")
        record(cat, "GET /v1/auth/ws-token unauth -> 401", status == 401, f"status={status}")
    except Exception as exc:
        record(cat, "GET /v1/auth/ws-token unauth -> 401", False, str(exc))

    # 4. GET /v1/portfolios without auth -> 401
    try:
        status, _, _ = http_json(f"{S9_BASE}/v1/portfolios")
        record(cat, "GET /v1/portfolios unauth -> 401", status == 401, f"status={status}")
    except Exception as exc:
        record(cat, "GET /v1/portfolios unauth -> 401", False, str(exc))

    # 5. GET /v1/portfolios with garbage token -> 401
    try:
        status, _, _ = http_json(f"{S9_BASE}/v1/portfolios", headers={"Authorization": "Bearer garbage.token.here"})
        record(cat, "GET /v1/portfolios garbage token -> 401", status == 401, f"status={status}")
    except Exception as exc:
        record(cat, "GET /v1/portfolios garbage token -> 401", False, str(exc))

    # 6. GET /v1/portfolios with empty Bearer -> 401
    try:
        status, _, _ = http_json(f"{S9_BASE}/v1/portfolios", headers={"Authorization": "Bearer "})
        record(cat, "GET /v1/portfolios empty Bearer -> 401", status == 401, f"status={status}")
    except Exception as exc:
        record(cat, "GET /v1/portfolios empty Bearer -> 401", False, str(exc))

    # 7. GET /v1/alerts/pending without auth -> 401
    try:
        status, _, _ = http_json(f"{S9_BASE}/v1/alerts/pending")
        record(cat, "GET /v1/alerts/pending unauth -> 401", status == 401, f"status={status}")
    except Exception as exc:
        record(cat, "GET /v1/alerts/pending unauth -> 401", False, str(exc))

    # 8. GET /v1/threads without auth -> 401
    try:
        status, _, _ = http_json(f"{S9_BASE}/v1/threads")
        record(cat, "GET /v1/threads unauth -> 401", status == 401, f"status={status}")
    except Exception as exc:
        record(cat, "GET /v1/threads unauth -> 401", False, str(exc))

    # 9. POST /v1/auth/logout -> 200
    try:
        status, _, _ = http_json(f"{S9_BASE}/v1/auth/logout", method="POST", headers=auth_hdr)
        # 200 or 204 both acceptable
        record(cat, "POST /v1/auth/logout -> 200", status in (200, 204), f"status={status}")
    except Exception as exc:
        record(cat, "POST /v1/auth/logout -> 200", False, str(exc))

    # 10. GET /healthz (no auth needed) -> 200
    try:
        status, _, _ = http_json(f"{S9_BASE}/healthz")
        record(cat, "GET /healthz no auth -> 200", status == 200, f"status={status}")
    except Exception as exc:
        record(cat, "GET /healthz no auth -> 200", False, str(exc))


# ===================================================================
# Category 2: Endpoint Coverage (13 tests)
# ===================================================================

# Endpoints that may fail due to known issues are marked with an expected_fail reason.
ENDPOINT_COVERAGE_TESTS: list[dict[str, Any]] = [
    {"method": "GET", "path": "/v1/portfolios", "expect": 200},
    {"method": "GET", "path": "/v1/watchlists", "expect": 200},
    {
        "method": "POST",
        "path": "/v1/fundamentals/screen",
        "body": {"filters": [{"metric": "market_cap", "operator": "gt", "value": 0}], "limit": 5, "offset": 0},
        "expect": 200,
    },
    {"method": "GET", "path": "/v1/fundamentals/screen/fields", "expect": 200, "auth": False},
    {"method": "GET", "path": "/v1/search/instruments?query=AAPL&limit=5", "expect": 200, "auth": False},
    {"method": "GET", "path": "/v1/alerts/pending?limit=5", "expect": 200},
    {"method": "GET", "path": "/v1/signals/ai", "expect": 200},
    {"method": "GET", "path": "/v1/signals/prediction-markets", "expect": 200},
    {"method": "GET", "path": "/v1/market/heatmap", "expect": 200},
    {"method": "GET", "path": "/v1/market/top-movers?type=gainers&limit=5", "expect": 200},
    {"method": "GET", "path": "/v1/map/layers", "expect": 200, "auth": False},
    {"method": "GET", "path": "/v1/email/preferences", "expect": 200},
    {"method": "GET", "path": "/v1/brokerage-connections", "expect": 200},
]

# Known issues — map endpoint path prefix to expected-fail reason.
# These endpoints may legitimately fail because the backing service is not
# fully wired up yet, or there is a known race condition.
KNOWN_ISSUES: dict[str, str] = {
    "/v1/signals/prediction-markets": "API-003 S4 Polymarket adapter not seeded",
    "/v1/brokerage-connections": "API-004 SnapTrade adapter not configured in dev",
    "/v1/threads": "API-002 S8 JWKS race on cold start",
    "/v1/signals/ai": "API-005 AI signals stub returns empty",
}


def _expected_fail_for(path: str) -> str | None:
    """Return the known-issue ID if this endpoint is expected to fail, else None."""
    bare = path.split("?")[0]
    for prefix, issue in KNOWN_ISSUES.items():
        if bare.startswith(prefix):
            return issue
    return None


def run_endpoint_coverage_tests(token: str) -> None:
    cat = "Endpoint Coverage"
    auth_hdr = {"Authorization": f"Bearer {token}"}

    for spec in ENDPOINT_COVERAGE_TESTS:
        method = spec["method"]
        path = spec["path"]
        expect = spec["expect"]
        needs_auth = spec.get("auth", True)
        body = spec.get("body")
        url = f"{S9_BASE}{path}"
        name = f"{method} {path.split('?')[0]} -> {expect}"
        ef = _expected_fail_for(path)

        try:
            headers = auth_hdr.copy() if needs_auth else {}
            status, _, data = http_json(url, method=method, headers=headers, body=body)
            passed = status == expect
            detail = f"status={status}"
            if not passed:
                detail += f" body={str(data)[:120]}"
            record(cat, name, passed, detail, expected_fail=ef if not passed else None)
        except Exception as exc:
            record(cat, name, False, str(exc)[:200], expected_fail=ef)


# ===================================================================
# Category 3: Response Schema Validation (8 tests)
# ===================================================================


def run_schema_validation_tests(token: str) -> None:
    cat = "Response Schema Validation"
    auth_hdr = {"Authorization": f"Bearer {token}"}

    # Helper to fetch JSON from an endpoint
    def fetch(path: str, *, method: str = "GET", body: dict | None = None, auth: bool = True) -> Any:
        headers = auth_hdr.copy() if auth else {}
        status, _, data = http_json(f"{S9_BASE}{path}", method=method, headers=headers, body=body)
        if status != 200:
            return None
        return data

    # 1. /v1/portfolios -> has "items" array, "total" int
    data = fetch("/v1/portfolios")
    if data is not None:
        ok = isinstance(data, dict) and isinstance(data.get("items"), list) and isinstance(data.get("total"), int)
        record(
            cat,
            '/v1/portfolios has "items" array and "total" int',
            ok,
            f"keys={list(data.keys()) if isinstance(data, dict) else type(data).__name__}",
        )
    else:
        record(cat, '/v1/portfolios has "items" array and "total" int', False, "endpoint did not return 200")

    # 2. /v1/watchlists -> is array with objects having id/watchlist_id, name
    # NOTE: S1 Portfolio returns "id" (not "watchlist_id") — the gateway proxies as-is.
    # The "members" field is only present on GET /v1/watchlists/{id} (single), not list.
    data = fetch("/v1/watchlists")
    if data is not None:

        def _check_wl(item: object) -> bool:
            return isinstance(item, dict) and ("watchlist_id" in item or "id" in item) and "name" in item

        if isinstance(data, list):
            if len(data) == 0:
                ok = True
                detail = "empty array (valid)"
            else:
                ok = _check_wl(data[0])
                detail = f"first_keys={list(data[0].keys()) if isinstance(data[0], dict) else type(data[0]).__name__}"
        elif isinstance(data, dict):
            items = data.get("items", data.get("watchlists", []))
            if isinstance(items, list) and len(items) == 0:
                ok = True
                detail = "wrapped empty array (valid)"
            elif isinstance(items, list) and len(items) > 0:
                ok = _check_wl(items[0])
                detail = (
                    f"first_keys={list(items[0].keys()) if isinstance(items[0], dict) else type(items[0]).__name__}"
                )
            else:
                ok = False
                detail = f"unexpected data shape: {str(data)[:120]}"
        else:
            ok = False
            detail = f"unexpected type: {type(data).__name__}"
        record(cat, "/v1/watchlists has watchlist objects", ok, detail)
    else:
        record(cat, "/v1/watchlists has watchlist objects", False, "endpoint did not return 200")

    # 3. /v1/alerts/pending -> has "alerts" array, "total" int
    data = fetch("/v1/alerts/pending?limit=5")
    if data is not None:
        ok = isinstance(data, dict) and isinstance(data.get("alerts"), list) and isinstance(data.get("total"), int)
        record(
            cat,
            '/v1/alerts/pending has "alerts" array and "total" int',
            ok,
            f"keys={list(data.keys()) if isinstance(data, dict) else type(data).__name__}",
        )
    else:
        record(cat, '/v1/alerts/pending has "alerts" array and "total" int', False, "endpoint did not return 200")

    # 4. /v1/fundamentals/screen -> has "results" array, "total" int
    data = fetch(
        "/v1/fundamentals/screen",
        method="POST",
        body={"filters": [{"metric": "market_cap", "operator": "gt", "value": 0}], "limit": 5, "offset": 0},
        auth=False,
    )
    if data is not None:
        ok = isinstance(data, dict) and isinstance(data.get("results"), list) and isinstance(data.get("total"), int)
        record(
            cat,
            '/v1/fundamentals/screen has "results" array and "total" int',
            ok,
            f"keys={list(data.keys()) if isinstance(data, dict) else type(data).__name__}",
        )
    else:
        record(cat, '/v1/fundamentals/screen has "results" array and "total" int', False, "endpoint did not return 200")

    # 5. /v1/search/instruments -> has "items" array, "total" int
    data = fetch("/v1/search/instruments?query=AAPL&limit=5", auth=False)
    if data is not None:
        ok = isinstance(data, dict) and isinstance(data.get("items"), list) and isinstance(data.get("total"), int)
        record(
            cat,
            '/v1/search/instruments has "items" array and "total" int',
            ok,
            f"keys={list(data.keys()) if isinstance(data, dict) else type(data).__name__}",
        )
    else:
        record(cat, '/v1/search/instruments has "items" array and "total" int', False, "endpoint did not return 200")

    # 6. /v1/market/heatmap -> has "sectors" array with 11 items
    data = fetch("/v1/market/heatmap")
    if data is not None:
        sectors = data.get("sectors") if isinstance(data, dict) else None
        ok = isinstance(sectors, list) and len(sectors) == 11
        detail = f"sectors_count={len(sectors) if isinstance(sectors, list) else 'N/A'}"
        record(cat, '/v1/market/heatmap has "sectors" array with 11 items', ok, detail)
    else:
        record(cat, '/v1/market/heatmap has "sectors" array with 11 items', False, "endpoint did not return 200")

    # 7. /v1/market/top-movers -> has "results" or "movers" array
    data = fetch("/v1/market/top-movers?type=gainers&limit=5")
    if data is not None:
        if isinstance(data, dict):
            ok = isinstance(data.get("results"), list) or isinstance(data.get("movers"), list)
            detail = f"keys={list(data.keys())}"
        else:
            ok = False
            detail = f"unexpected type: {type(data).__name__}"
        record(cat, '/v1/market/top-movers has "results" or "movers" array', ok, detail)
    else:
        record(cat, '/v1/market/top-movers has "results" or "movers" array', False, "endpoint did not return 200")

    # 8. /v1/auth/dev-login -> has access_token, user, token_type, expires_in
    status, _, data = http_json(f"{S9_BASE}/v1/auth/dev-login", method="POST")
    if status == 200 and isinstance(data, dict):
        ok = all(k in data for k in ("access_token", "user", "token_type", "expires_in"))
        detail = f"keys={list(data.keys())}"
        record(cat, "/v1/auth/dev-login has required response fields", ok, detail)
    else:
        record(cat, "/v1/auth/dev-login has required response fields", False, f"status={status}")


# ===================================================================
# Category 4: Security Tests (8 tests)
# ===================================================================


def run_security_tests(token: str) -> None:
    cat = "Security Tests"
    auth_hdr = {"Authorization": f"Bearer {token}"}

    # 1. SQL injection in search
    try:
        status, _, data = http_json(f"{S9_BASE}/v1/search/instruments?query=%27%20OR%201%3D1--&limit=5")
        # Should return 200 with empty or safe results — NOT a DB error (500)
        ok = status in (200, 400, 422)
        if status == 200 and isinstance(data, dict):
            items = data.get("items", [])
            detail = f"status={status}, items_count={len(items)}"
        else:
            detail = f"status={status}"
        record(cat, "SQL injection in search returns safe response", ok, detail)
    except Exception as exc:
        record(cat, "SQL injection in search returns safe response", False, str(exc)[:200])

    # 2. XSS in search — script tags should not appear in response
    try:
        status, _, raw_body = http_request(
            f"{S9_BASE}/v1/search/instruments?query=%3Cscript%3Ealert(1)%3C/script%3E&limit=5"
        )
        body_str = raw_body.decode("utf-8", errors="replace")
        # The response should not reflect the raw <script> tag
        reflected = "<script>alert(1)</script>" in body_str
        ok = not reflected
        record(cat, "XSS in search: script tags not reflected", ok, f"status={status}, reflected={reflected}")
    except Exception as exc:
        record(cat, "XSS in search: script tags not reflected", False, str(exc)[:200])

    # 3. Path traversal
    try:
        status, _, _ = http_request(f"{S9_BASE}/v1/../../../etc/passwd")
        ok = status in (400, 404, 405)
        record(cat, "Path traversal returns 404/400", ok, f"status={status}")
    except Exception as exc:
        record(cat, "Path traversal returns 404/400", False, str(exc)[:200])

    # 4. IDOR — portfolio holdings with fabricated ID
    try:
        fake_id = "00000000-0000-0000-0000-000000000001"
        status, _, _ = http_json(f"{S9_BASE}/v1/holdings/{fake_id}", headers=auth_hdr)
        # Should be 404 (not found for this user) — NOT 200 with other user's data
        ok = status in (403, 404)
        record(cat, f"IDOR portfolio holdings -> {status} (expected 403/404)", ok, f"status={status}")
    except Exception as exc:
        record(cat, "IDOR portfolio holdings -> 403/404", False, str(exc)[:200])

    # 5. IDOR — watchlist with fabricated ID
    try:
        fake_id = "00000000-0000-0000-0000-000000000001"
        status, _, _ = http_json(f"{S9_BASE}/v1/watchlists/{fake_id}", headers=auth_hdr)
        ok = status in (403, 404)
        record(cat, f"IDOR watchlist -> {status} (expected 403/404)", ok, f"status={status}")
    except Exception as exc:
        record(cat, "IDOR watchlist -> 403/404", False, str(exc)[:200])

    # 6. CORS — OPTIONS with evil origin should not be allowed
    try:
        req = urllib.request.Request(
            f"{S9_BASE}/healthz",
            method="OPTIONS",
            headers={
                "Origin": "https://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        resp = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
        resp_headers = {k.lower(): v for k, v in resp.getheaders()}
        acao = resp_headers.get("access-control-allow-origin", "")
        ok = acao != "https://evil.com" and acao != "*"
        record(cat, "CORS rejects evil.com origin", ok, f"Access-Control-Allow-Origin={acao!r}")
    except urllib.error.HTTPError as e:
        # A 4xx on OPTIONS from evil origin is also acceptable
        resp_headers = {k.lower(): v for k, v in e.headers.items()}
        acao = resp_headers.get("access-control-allow-origin", "")
        ok = acao != "https://evil.com" and acao != "*"
        record(cat, "CORS rejects evil.com origin", ok, f"status={e.code}, Access-Control-Allow-Origin={acao!r}")
    except Exception as exc:
        record(cat, "CORS rejects evil.com origin", False, str(exc)[:200])

    # 7. Rate limiting — 25 rapid unauthenticated requests should trigger 429
    try:
        got_429 = False
        for _ in range(25):
            try:
                status, _, _ = http_request(f"{S9_BASE}/healthz", timeout=2)
                if status == 429:
                    got_429 = True
                    break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    got_429 = True
                    break
            except Exception:  # noqa: S110
                pass  # Individual request failures are expected during burst
        record(
            cat,
            "Rate limiting: 25 rapid requests trigger 429",
            got_429,
            f"got_429={got_429}",
            expected_fail="SEC-006 rate limiting requires Valkey" if not got_429 else None,
        )
    except Exception as exc:
        record(
            cat,
            "Rate limiting: 25 rapid requests trigger 429",
            False,
            str(exc)[:200],
            expected_fail="SEC-006 rate limiting requires Valkey",
        )

    # 8. Security headers on S9
    try:
        _, resp_headers, _ = http_request(f"{S9_BASE}/healthz")
        has_xfo = "x-frame-options" in resp_headers
        has_xcto = "x-content-type-options" in resp_headers
        ok = has_xfo and has_xcto
        detail_parts = []
        if has_xfo:
            detail_parts.append(f"X-Frame-Options={resp_headers['x-frame-options']}")
        else:
            detail_parts.append("X-Frame-Options=MISSING")
        if has_xcto:
            detail_parts.append(f"X-Content-Type-Options={resp_headers['x-content-type-options']}")
        else:
            detail_parts.append("X-Content-Type-Options=MISSING")
        record(cat, "Security headers present (XFO + XCTO)", ok, ", ".join(detail_parts))
    except Exception as exc:
        record(cat, "Security headers present (XFO + XCTO)", False, str(exc)[:200])


# ===================================================================
# Category 5: Frontend Smoke Tests (6 tests)
# ===================================================================


def run_frontend_smoke_tests() -> None:
    cat = "Frontend Smoke"

    # 1. GET / -> 200
    try:
        status, _, _ = http_request(f"{FRONTEND_BASE}/")
        record(cat, f"GET {FRONTEND_BASE}/ -> 200", status == 200, f"status={status}")
    except Exception as exc:
        record(cat, f"GET {FRONTEND_BASE}/ -> 200", False, str(exc)[:200])

    # 2. GET /login -> 200
    try:
        status, _, _ = http_request(f"{FRONTEND_BASE}/login")
        record(cat, f"GET {FRONTEND_BASE}/login -> 200", status == 200, f"status={status}")
    except Exception as exc:
        record(cat, f"GET {FRONTEND_BASE}/login -> 200", False, str(exc)[:200])

    # 3. GET /dashboard -> 200
    try:
        status, _, _ = http_request(f"{FRONTEND_BASE}/dashboard")
        # Next.js may return 200 (SSR) or 307 (redirect to login) — both are valid
        ok = status in (200, 307, 308)
        record(cat, f"GET {FRONTEND_BASE}/dashboard -> 200", ok, f"status={status}")
    except Exception as exc:
        record(cat, f"GET {FRONTEND_BASE}/dashboard -> 200", False, str(exc)[:200])

    # 4. GET /nonexistent -> 404
    try:
        status, _, _ = http_request(f"{FRONTEND_BASE}/nonexistent")
        record(cat, f"GET {FRONTEND_BASE}/nonexistent -> 404", status == 404, f"status={status}")
    except Exception as exc:
        record(cat, f"GET {FRONTEND_BASE}/nonexistent -> 404", False, str(exc)[:200])

    # 5. Security headers on frontend
    try:
        _, resp_headers, _ = http_request(f"{FRONTEND_BASE}/")
        has_xfo = "x-frame-options" in resp_headers
        has_xcto = "x-content-type-options" in resp_headers
        has_rp = "referrer-policy" in resp_headers
        ok = has_xfo and has_xcto and has_rp
        parts = []
        for hdr, present in [
            ("X-Frame-Options", has_xfo),
            ("X-Content-Type-Options", has_xcto),
            ("Referrer-Policy", has_rp),
        ]:
            parts.append(f"{hdr}={'present' if present else 'MISSING'}")
        record(cat, "Frontend security headers (XFO, XCTO, Referrer-Policy)", ok, ", ".join(parts))
    except Exception as exc:
        record(cat, "Frontend security headers (XFO, XCTO, Referrer-Policy)", False, str(exc)[:200])

    # 6. No X-Powered-By header
    try:
        _, resp_headers, _ = http_request(f"{FRONTEND_BASE}/")
        has_xpb = "x-powered-by" in resp_headers
        record(
            cat,
            "No X-Powered-By header on frontend",
            not has_xpb,
            f"X-Powered-By={'present (' + resp_headers.get('x-powered-by', '') + ')' if has_xpb else 'absent'}",
        )
    except Exception as exc:
        record(cat, "No X-Powered-By header on frontend", False, str(exc)[:200])


# ===================================================================
# Category 6: Infrastructure Health (5 tests)
# ===================================================================


def run_infrastructure_health_tests() -> None:
    cat = "Infrastructure Health"

    # 1. GET /healthz -> 200
    try:
        status, _, _ = http_json(f"{S9_BASE}/healthz")
        record(cat, "GET /healthz -> 200", status == 200, f"status={status}")
    except Exception as exc:
        record(cat, "GET /healthz -> 200", False, str(exc)[:200])

    # 2. GET /readyz -> 200
    try:
        status, _, _ = http_json(f"{S9_BASE}/readyz")
        record(cat, "GET /readyz -> 200", status == 200, f"status={status}")
    except Exception as exc:
        record(cat, "GET /readyz -> 200", False, str(exc)[:200])

    # 3. GET /internal/jwks -> 200 with RSA key
    try:
        status, _, data = http_json(f"{S9_BASE}/internal/jwks")
        has_keys = (
            status == 200
            and isinstance(data, dict)
            and "keys" in data
            and isinstance(data["keys"], list)
            and len(data["keys"]) > 0
        )
        if has_keys:
            first_key = data["keys"][0]
            is_rsa = first_key.get("kty") == "RSA"
            ok = is_rsa
            detail = f"kty={first_key.get('kty')}, alg={first_key.get('alg')}"
        else:
            ok = False
            detail = f"status={status}, keys_present={has_keys}"
        record(cat, "GET /internal/jwks -> 200 with RSA key", ok, detail)
    except Exception as exc:
        record(cat, "GET /internal/jwks -> 200 with RSA key", False, str(exc)[:200])

    # 4. GET /metrics -> 200 with prometheus format
    try:
        status, _, raw = http_request(f"{S9_BASE}/metrics")
        body_str = raw.decode("utf-8", errors="replace")
        # Prometheus format has lines like "# HELP ..." or "# TYPE ..."
        has_prometheus = bool(re.search(r"^# (HELP|TYPE) ", body_str, re.MULTILINE))
        ok = status == 200 and has_prometheus
        record(
            cat,
            "GET /metrics -> 200 with prometheus format",
            ok,
            f"status={status}, has_prometheus_markers={has_prometheus}",
        )
    except Exception as exc:
        record(cat, "GET /metrics -> 200 with prometheus format", False, str(exc)[:200])

    # 5. GET /docs -> 200 (OpenAPI)
    # Also accept 429 — docs is a low-priority check that can be rate-limited
    try:
        status, _, _ = http_request(f"{S9_BASE}/docs")
        record(cat, "GET /docs -> 200 (OpenAPI)", status in (200, 429), f"status={status}")
    except Exception as exc:
        record(cat, "GET /docs -> 200 (OpenAPI)", False, str(exc)[:200])


# ===================================================================
# Report & Main
# ===================================================================


def print_report() -> None:
    """Print the final structured report and return exit code."""
    print("\n" + "=" * 60)
    print("  Worldview Exhaustive QA Report")
    print("=" * 60)

    # Group by category, preserving insertion order
    categories: list[str] = []
    by_cat: dict[str, list[tuple[str, str, str, str]]] = {}
    for cat, name, status, detail in RESULTS:
        if cat not in by_cat:
            categories.append(cat)
            by_cat[cat] = []
        by_cat[cat].append((cat, name, status, detail))

    total = 0
    passed = 0
    failed = 0
    expected_fail = 0

    for cat in categories:
        print(f"\nCategory: {cat}")
        for _, name, status, detail in by_cat[cat]:
            total += 1
            if status == "PASS":
                passed += 1
                icon = "\u2713"  # checkmark
                suffix = ""
            elif status == "EXPECTED_FAIL":
                expected_fail += 1
                icon = "\u26a0"  # warning
                suffix = f" [EXPECTED_FAIL: {detail}]"
            else:
                failed += 1
                icon = "\u2717"  # cross
                suffix = f" -- {detail}"
            print(f"  {icon} {name}{suffix}")

    print(f"\n{'=' * 60}")
    print("  Summary")
    print(f"{'=' * 60}")
    print(f"  Total: {total} | Pass: {passed} | Fail: {failed} | Expected Fail: {expected_fail}")

    exit_code = 1 if failed > 0 else 0
    print(f"  Exit code: {exit_code}")
    print()

    return exit_code  # type: ignore[return-value]


def main() -> int:
    print("Worldview Exhaustive QA — starting...")
    print(f"  S9 target:       {S9_BASE}")
    print(f"  Frontend target:  {FRONTEND_BASE}")
    print(f"  Request timeout:  {REQUEST_TIMEOUT}s")
    print()

    # Pre-flight: check S9 is reachable
    if not check_connectivity():
        print("[FATAL] Cannot reach S9 at {S9_BASE}/healthz.")
        print("        Is the dev stack running? (make dev)")
        return 1

    print("[OK] S9 is reachable.")

    # Obtain auth token via dev-login
    print("[..] Obtaining dev-login token...")
    token = obtain_dev_token()
    if token is None:
        print("[FATAL] Could not obtain dev-login token.")
        print("        Is OIDC_DISCOVERY_OPTIONAL=true in the gateway config?")
        return 1

    print(f"[OK] Got token: {token[:20]}...{token[-10:]}")
    print()

    # ── Run all test categories ──────────────────────────────────────────
    start = time.monotonic()

    print("[..] Running Auth Boundary Tests...")
    run_auth_boundary_tests(token)

    print("[..] Running Endpoint Coverage Tests...")
    run_endpoint_coverage_tests(token)

    print("[..] Running Response Schema Validation Tests...")
    run_schema_validation_tests(token)

    print("[..] Running Security Tests...")
    run_security_tests(token)

    print("[..] Running Frontend Smoke Tests...")
    run_frontend_smoke_tests()

    print("[..] Running Infrastructure Health Tests...")
    run_infrastructure_health_tests()

    elapsed = time.monotonic() - start
    print(f"\n[DONE] All tests completed in {elapsed:.1f}s")

    # ── Print report and exit ────────────────────────────────────────────
    exit_code = print_report()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
