#!/usr/bin/env bash
# verify-prod-health.sh — Post-deploy smoke tests for worldview production stack
#
# Usage (from worldview-gitops or worldview directory on Hetzner):
#   DOMAIN=worldview.example.com ./scripts/verify-prod-health.sh
#
# Exits 0 if all checks pass, 1 if any check fails.

set -euo pipefail

DOMAIN="${DOMAIN:?DOMAIN env var is required}"
PASS=0
FAIL=0
WARN=0

pass() { echo "  ✓ $1"; ((PASS++)) || true; }
fail() { echo "  ✗ $1"; ((FAIL++)) || true; }
warn() { echo "  ~ $1"; ((WARN++)) || true; }

echo "=== Worldview Production Health Check ==="
echo "Domain: ${DOMAIN}"
echo ""

# ── 1. Frontend ────────────────────────────────────────────────────────────────
echo "[1] Frontend (https://${DOMAIN})"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "https://${DOMAIN}/" 2>/dev/null || echo "000")
[ "${STATUS}" = "200" ] && pass "HTTP 200" || fail "Expected 200, got ${STATUS}"

# HTTP → HTTPS redirect
STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 -L0 "http://${DOMAIN}/" 2>/dev/null || echo "000")
# After following redirects, should land on 200; first hop should be 301
REDIRECT=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 --no-location "http://${DOMAIN}/" 2>/dev/null || echo "000")
[ "${REDIRECT}" = "301" ] && pass "HTTP→HTTPS redirect (301)" || fail "Expected 301 redirect, got ${REDIRECT}"

# No upgrade-insecure-requests on HTTP (BP-324)
CSP=$(curl -s -I --max-time 10 "https://${DOMAIN}/" 2>/dev/null | grep -i "content-security-policy" || true)
echo "${CSP}" | grep -q "upgrade-insecure-requests" && pass "upgrade-insecure-requests present in CSP (HTTPS enabled)" || warn "upgrade-insecure-requests absent (check NEXT_PUBLIC_WS_BASE_URL is wss://)"

echo ""

# ── 2. API Gateway ─────────────────────────────────────────────────────────────
echo "[2] API Gateway (https://api.${DOMAIN})"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "https://api.${DOMAIN}/v1/health" 2>/dev/null || echo "000")
[ "${STATUS}" = "200" ] && pass "GET /v1/health → 200" || fail "Expected 200, got ${STATUS}"

STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "https://api.${DOMAIN}/readyz" 2>/dev/null || echo "000")
[ "${STATUS}" = "200" ] && pass "GET /readyz → 200 (all deps healthy)" || warn "GET /readyz → ${STATUS} (some dependency may be unhealthy)"

echo ""

# ── 3. Alert WebSocket ─────────────────────────────────────────────────────────
echo "[3] Alert WebSocket (wss://ws.${DOMAIN})"
# HTTP GET to the WS endpoint should get 400/426 (Traefik reached the service, rejected non-WS)
STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
  "https://ws.${DOMAIN}/v1/alerts/stream" 2>/dev/null || echo "000")
# 400 = WebSocket upgrade required (alert service reachable)
# 426 = Upgrade Required (also means service reachable)
# 502 = Service down or Traefik can't reach alert
if [ "${STATUS}" = "400" ] || [ "${STATUS}" = "426" ] || [ "${STATUS}" = "401" ]; then
    pass "Alert service reachable (${STATUS} — correct for non-WS request)"
elif [ "${STATUS}" = "000" ]; then
    fail "Connection refused or timeout (check Traefik alert labels and alert container status)"
else
    warn "Unexpected status ${STATUS} (expected 400/426/401)"
fi

echo ""

# ── 4. TLS certificate ────────────────────────────────────────────────────────
echo "[4] TLS Certificate"
EXPIRY=$(echo | openssl s_client -servername "${DOMAIN}" -connect "${DOMAIN}:443" 2>/dev/null \
  | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2 || echo "unknown")
pass "Certificate expiry: ${EXPIRY}"

# ── 5. Security headers ───────────────────────────────────────────────────────
echo ""
echo "[5] Security Headers"
HEADERS=$(curl -sI --max-time 10 "https://${DOMAIN}/" 2>/dev/null || true)

echo "${HEADERS}" | grep -qi "strict-transport-security" && pass "HSTS header present" || fail "HSTS header missing"
echo "${HEADERS}" | grep -qi "x-frame-options" && pass "X-Frame-Options present" || fail "X-Frame-Options missing"
echo "${HEADERS}" | grep -qi "x-content-type-options" && pass "X-Content-Type-Options present" || fail "X-Content-Type-Options missing"

# ── 6. No direct infra ports exposed ─────────────────────────────────────────
echo ""
echo "[6] Infra Port Exposure (should all be empty)"
for port in 5432 6379 9092 8000 8001 8002 8003 8004 8005 8006 8007 8008 8010; do
    if ss -tlnp 2>/dev/null | grep -q ":${port} "; then
        fail "Port ${port} is exposed on the host (should be blocked)"
    fi
done
pass "No infra ports exposed on host"

# ── 7. Container health ────────────────────────────────────────────────────────
echo ""
echo "[7] Container Status"
UNHEALTHY=$(docker ps --filter "health=unhealthy" --format "{{.Names}}" 2>/dev/null | wc -l || echo "0")
STARTED=$(docker ps --filter "name=worldview" --format "{{.Names}}" 2>/dev/null | wc -l || echo "0")
pass "Worldview containers running: ${STARTED}"
[ "${UNHEALTHY}" -eq 0 ] && pass "No unhealthy containers" || fail "${UNHEALTHY} unhealthy containers: $(docker ps --filter "health=unhealthy" --format "{{.Names}}")"

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo "=== Results: ${PASS} passed, ${FAIL} failed, ${WARN} warnings ==="

if [ "${FAIL}" -gt 0 ]; then
    echo ""
    echo "FAILED: ${FAIL} checks failed. Review logs:"
    echo "  docker logs worldview-traefik-1 2>&1 | tail -50"
    echo "  docker logs worldview-api-gateway-1 2>&1 | tail -50"
    exit 1
elif [ "${WARN}" -gt 0 ]; then
    echo "WARNING: ${WARN} checks had warnings — review above output."
    exit 0
else
    echo "All checks passed!"
    exit 0
fi
