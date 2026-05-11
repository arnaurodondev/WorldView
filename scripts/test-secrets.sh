#!/usr/bin/env bash
# scripts/test-secrets.sh — Verify all SOPS-encrypted secret files can be decrypted.
#
# Run after generating or modifying secrets in infra/k8s/secrets/.
# Requires the Age private key in ~/.config/sops/age/keys.txt (or SOPS_AGE_KEY_FILE env var).
#
# Usage:
#   ./scripts/test-secrets.sh [--dir <path>]
#
# Options:
#   --dir <path>    Directory to scan (default: infra/k8s/secrets)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

SECRET_DIR="$ROOT_DIR/infra/k8s/secrets"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dir) SECRET_DIR="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--dir <path>]"
            exit 0
            ;;
        *) echo "Unknown argument: $1"; exit 2 ;;
    esac
done

if ! command -v sops &>/dev/null; then
    echo "ERROR: sops is not installed. Install with: brew install sops"
    exit 1
fi

if [[ ! -d "$SECRET_DIR" ]]; then
    echo "Secret directory does not exist yet: $SECRET_DIR"
    echo "Run ./scripts/generate-secrets.sh first (after setting up Age key)."
    exit 0
fi

mapfile -t FILES < <(find "$SECRET_DIR" -maxdepth 1 -name "*.yaml" 2>/dev/null)
if [[ ${#FILES[@]} -eq 0 ]]; then
    echo "No secret files found in $SECRET_DIR — nothing to test."
    exit 0
fi

echo "========================================"
echo "  SOPS decrypt test"
echo "  Directory: $SECRET_DIR"
echo "========================================"

PASS=0
FAIL=0

for f in "$SECRET_DIR"/*.yaml; do
    fname=$(basename "$f")

    # Check the file is actually SOPS-encrypted (must contain sops: metadata)
    if ! grep -q "sops:" "$f" 2>/dev/null; then
        echo "  WARN: $fname — does not appear to be SOPS-encrypted (missing 'sops:' key)"
        ((FAIL++)) || true
        continue
    fi

    if sops --decrypt "$f" > /dev/null 2>&1; then
        echo "  OK: $fname"
        ((PASS++)) || true
    else
        echo "  FAIL: $fname — decryption failed"
        echo "        Check that SOPS_AGE_KEY_FILE or ~/.config/sops/age/keys.txt is set correctly."
        ((FAIL++)) || true
    fi
done

echo ""
echo "========================================"
echo "  Results: $PASS OK, $FAIL FAIL"
echo "========================================"

[[ $FAIL -eq 0 ]] || exit 1
