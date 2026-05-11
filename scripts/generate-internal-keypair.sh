#!/usr/bin/env bash
# generate-internal-keypair.sh — Generate RSA-2048 keypair for S9 internal JWT signing
# Usage: ./scripts/generate-internal-keypair.sh
# Output: env var declarations for API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY and PUBLIC_KEY

set -euo pipefail

PRIVATE_KEY_FILE=$(mktemp /tmp/internal_jwt_key_XXXXXX.pem)
PUBLIC_KEY_FILE=$(mktemp /tmp/internal_jwt_key_XXXXXX.pub)

# Ensure temp files are removed on exit (even on error)
trap 'rm -f "$PRIVATE_KEY_FILE" "$PUBLIC_KEY_FILE"' EXIT

openssl genrsa -out "$PRIVATE_KEY_FILE" 2048 2>/dev/null
openssl rsa -in "$PRIVATE_KEY_FILE" -pubout -out "$PUBLIC_KEY_FILE" 2>/dev/null

echo "=== Add to your .env file (or services/api-gateway/.env) ==="
echo ""
# Encode PEM as single-line env var: replace newlines with literal \n
echo "API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY=\"$(awk '{printf "%s\\n", $0}' "$PRIVATE_KEY_FILE")\""
echo "API_GATEWAY_INTERNAL_JWT_PUBLIC_KEY=\"$(awk '{printf "%s\\n", $0}' "$PUBLIC_KEY_FILE")\""
echo ""
echo "=== Done. Keep the private key secret — never commit it to git. ==="
