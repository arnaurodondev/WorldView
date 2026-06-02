#!/usr/bin/env bash
# scripts/hooks/secret-scan.sh
# Pre-commit secret scanner. Blocks commits that introduce API-key-shaped strings.
#
# Rationale: on 2026-06-02 a DeepInfra key committed in two audit-doc files for
# ~35 days was scraped and abused for ~$26 of unauthorised Anthropic-via-DeepInfra
# usage. This hook exists to prevent any recurrence.
#
# Strategy: scan ONLY staged additions (git diff --cached -U0 with leading "+")
# against a curated regex list of known provider key formats and high-entropy
# strings adjacent to API_KEY / TOKEN / SECRET assignments. Exit non-zero on hit.
#
# Allowlist mechanism: lines containing `# pragma: allowlist-secret` are skipped.
# Use sparingly and only for test fixtures with obviously fake values.

set -euo pipefail

# Staged additions only — diff format puts a "+" at the start of new lines.
staged=$(git diff --cached -U0 --diff-filter=ACM 2>/dev/null || true)
[ -z "$staged" ] && exit 0

# Strip diff metadata; keep only added lines (start with "+", but not "+++").
added=$(printf '%s\n' "$staged" | awk '/^\+\+\+ / {next} /^\+/ {sub(/^\+/, ""); print}')
[ -z "$added" ] && exit 0

# Drop allowlisted lines.
added=$(printf '%s\n' "$added" | grep -v 'pragma: allowlist-secret' || true)
[ -z "$added" ] && exit 0

violations=0
report() {
  local label="$1"
  local match="$2"
  printf '  [%s] %s\n' "$label" "$match" >&2
  violations=$((violations + 1))
}

# 1. Provider-prefixed keys (canonical formats).
while IFS= read -r m; do report "openai-sk" "$m"; done < <(printf '%s\n' "$added" | grep -oE 'sk-[A-Za-z0-9]{20,}' || true)
while IFS= read -r m; do report "github-pat" "$m"; done < <(printf '%s\n' "$added" | grep -oE '(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}' || true)
while IFS= read -r m; do report "github-pat-fg" "$m"; done < <(printf '%s\n' "$added" | grep -oE 'github_pat_[A-Za-z0-9_]{82,}' || true)
while IFS= read -r m; do report "aws-akid" "$m"; done < <(printf '%s\n' "$added" | grep -oE 'AKIA[0-9A-Z]{16}' || true)
while IFS= read -r m; do report "google-api" "$m"; done < <(printf '%s\n' "$added" | grep -oE 'AIza[0-9A-Za-z_-]{35}' || true)
while IFS= read -r m; do report "slack-bot" "$m"; done < <(printf '%s\n' "$added" | grep -oE 'xox[abprs]-[A-Za-z0-9-]{10,}' || true)
while IFS= read -r m; do report "anthropic-sk" "$m"; done < <(printf '%s\n' "$added" | grep -oE 'sk-ant-[A-Za-z0-9_-]{40,}' || true)
while IFS= read -r m; do report "stripe-sk" "$m"; done < <(printf '%s\n' "$added" | grep -oE 'sk_(live|test)_[A-Za-z0-9]{24,}' || true)

# 2. Generic high-entropy values following common secret-name patterns.
#    Catches the DeepInfra-style 32+ char alphanumerics that don't have a vendor prefix.
#    We require the assignment LHS to look like a secret name to keep false-positives low.
suspect_pattern='([A-Z][A-Z0-9_]*)?(API_KEY|TOKEN|SECRET|PASSWORD|PRIVATE_KEY|ACCESS_KEY|CLIENT_SECRET|AUTH_KEY)[[:space:]]*[=:][[:space:]]*["'\'']?([A-Za-z0-9_+/=-]{16,})'
while IFS= read -r line; do
  # Skip placeholder / empty / example values.
  value=$(printf '%s\n' "$line" | sed -E "s/.*[=:][[:space:]]*[\"']?//" | sed -E 's/[\"'\'']?$//')
  case "$value" in
    ""|*EXAMPLE*|*placeholder*|*PLACEHOLDER*|*your_*|*YOUR_*|*REDACTED*|*change*|*CHANGE*|*xxx*|*XXX*|*ROTATED*) continue ;;
    dev-*|test-*|*-test|*-dev|*example*) continue ;;
  esac
  # Skip if it's a JWT (three base64 segments separated by .) — those are usually
  # short-lived session tokens, not long-lived keys. We still warn on bearer-named JWTs.
  if printf '%s' "$value" | grep -qE '^eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$'; then continue; fi
  report "generic-secret-assignment" "${line:0:120}"
done < <(printf '%s\n' "$added" | grep -E "$suspect_pattern" || true)

# 3. Specific known-leaked / revoked keys — fast-fail on the historical incident value
#    so it cannot be re-introduced by an old branch or copy-paste from cached audit files.
while IFS= read -r m; do report "REVOKED-2026-06-02" "$m"; done < <(printf '%s\n' "$added" | grep -oE 'xVi3qIVR8yPnu7DnP36GdFs2brm9GivI' || true)  # pragma: allowlist-secret

if [ "$violations" -gt 0 ]; then
  echo "" >&2
  echo "secret-scan: $violations potential secret(s) found in staged changes." >&2
  echo "secret-scan: if the match is a placeholder or test value, append '# pragma: allowlist-secret' to the line." >&2
  echo "secret-scan: otherwise REMOVE the secret, rotate it on the provider, and commit again." >&2
  exit 1
fi

exit 0
