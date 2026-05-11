#!/usr/bin/env bash
# scripts/test-alertmanager-email.sh — Fire a test alert through Alertmanager to verify SMTP delivery.
#
# Prerequisites:
#   - Monitoring stack running: docker compose --profile monitoring up -d
#   - Alertmanager configured with SMTP credentials in infra/alertmanager/alertmanager.yml
#
# Usage:
#   ./scripts/test-alertmanager-email.sh [--url <alertmanager-url>]
#   ./scripts/test-alertmanager-email.sh --resolve   # resolve previously fired test alert

set -euo pipefail

ALERTMANAGER_URL="${ALERTMANAGER_URL:-http://localhost:9093}"
RESOLVE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --url) ALERTMANAGER_URL="$2"; shift 2 ;;
        --resolve) RESOLVE=true; shift ;;
        -h|--help)
            echo "Usage: $0 [--url <alertmanager-url>] [--resolve]"
            exit 0
            ;;
        *) echo "Unknown argument: $1"; exit 2 ;;
    esac
done

if ! command -v curl &>/dev/null; then
    echo "ERROR: curl is required"
    exit 1
fi

# Check Alertmanager is reachable
if ! curl -s --connect-timeout 3 "$ALERTMANAGER_URL/-/healthy" > /dev/null; then
    echo "ERROR: Alertmanager not reachable at $ALERTMANAGER_URL"
    echo "Start monitoring stack: docker compose --profile monitoring up -d"
    exit 1
fi

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)

if $RESOLVE; then
    echo "Resolving test alert..."
    curl -s -X POST "$ALERTMANAGER_URL/api/v2/alerts" \
        -H "Content-Type: application/json" \
        -d "[{
          \"labels\": {
            \"alertname\": \"DeploymentSmokeTest\",
            \"severity\": \"info\",
            \"namespace\": \"worldview\"
          },
          \"endsAt\": \"$NOW\"
        }]"
    echo ""
    echo "Test alert resolved."
    exit 0
fi

echo "========================================"
echo "  Alertmanager email smoke test"
echo "  URL: $ALERTMANAGER_URL"
echo "========================================"
echo ""
echo "Firing test alert..."

HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$ALERTMANAGER_URL/api/v2/alerts" \
    -H "Content-Type: application/json" \
    -d "[{
      \"labels\": {
        \"alertname\": \"DeploymentSmokeTest\",
        \"severity\": \"info\",
        \"namespace\": \"worldview\",
        \"service\": \"smoke-test\"
      },
      \"annotations\": {
        \"summary\": \"[worldview] Alertmanager email delivery smoke test\",
        \"description\": \"This is a test alert fired from scripts/test-alertmanager-email.sh. If you receive this email, SMTP delivery is working correctly.\"
      },
      \"startsAt\": \"$NOW\"
    }]")

if [[ "$HTTP_STATUS" == "200" ]]; then
    echo "  OK: Alert accepted by Alertmanager (HTTP $HTTP_STATUS)"
else
    echo "  FAIL: Alertmanager returned HTTP $HTTP_STATUS"
    exit 1
fi

echo ""
echo "Alert fired successfully."
echo ""
echo "Next steps:"
echo "  1. Check your inbox at the configured ALERT_EMAIL_RECIPIENT address"
echo "     Email should arrive within 2-5 minutes (Alertmanager group_wait=30s)"
echo "  2. Check Alertmanager UI: $ALERTMANAGER_URL"
echo "  3. Check SMTP credentials in infra/alertmanager/alertmanager.yml"
echo "  4. To resolve the test alert: $0 --resolve"
echo ""
echo "If no email arrives within 5 minutes:"
echo "  - Verify SMTP_USER and SMTP_PASSWORD in alertmanager.yml"
echo "  - Verify Brevo sender domain is verified (SPF/DKIM records set)"
echo "  - Check Alertmanager logs: docker compose --profile monitoring logs alertmanager"
