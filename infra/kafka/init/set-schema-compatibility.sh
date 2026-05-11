#!/bin/sh
# PLAN-0057 follow-up Wave A (D-004): pin Schema Registry compatibility level.
#
# Iterates over every ``<topic>-value`` subject in the registry and PUTs a
# subject-level ``{"compatibility":"BACKWARD"}`` config. This guards against a
# future operator bootstrapping the registry with a different default
# (e.g. ``NONE``), which would let a backwards-incompatible v3 schema register
# silently and break older consumers.
#
# Idempotent: re-runs are no-ops if the level is already BACKWARD.
#
# Special case: ``relation.type.proposed.v1-value`` is intentionally pinned to
# ``FULL`` by ``register-schemas.py`` because both FORWARD and BACKWARD checks
# matter for that subject. We skip it here so we don't downgrade it.
#
# Environment variables:
#   SCHEMA_REGISTRY_URL  — base URL (default: http://localhost:8081)
#   COMPAT_LEVEL         — compatibility level to set (default: BACKWARD)
#
# Exit codes:
#   0  — every subject pinned (or skipped intentionally)
#   1  — at least one subject failed; see stderr
#
# Usage (host):  bash infra/kafka/init/set-schema-compatibility.sh
# Usage (compose): runs as the ``schema-compat-init`` one-shot init container.

set -eu

REGISTRY_URL="${SCHEMA_REGISTRY_URL:-http://localhost:8081}"
COMPAT_LEVEL="${COMPAT_LEVEL:-BACKWARD}"
# Subjects that intentionally require a stricter compatibility level — leave
# them alone so we never DOWNGRADE a registered policy.
SKIP_SUBJECTS="relation.type.proposed.v1-value"

echo "[set-schema-compat] registry=${REGISTRY_URL} level=${COMPAT_LEVEL}"

# Fetch the list of subjects. The endpoint returns a JSON array; we cheat a
# tiny bit and avoid taking a hard dependency on jq by parsing with sed.
subjects_json="$(curl -fsS "${REGISTRY_URL}/subjects")"
# Strip [], split on commas, strip quotes/whitespace.
subjects="$(echo "${subjects_json}" \
    | sed -e 's/^\[//' -e 's/\]$//' -e 's/","/\n/g' -e 's/"//g' -e 's/^ *//' -e 's/ *$//')"

if [ -z "${subjects}" ]; then
    echo "[set-schema-compat] no subjects registered yet — nothing to pin"
    exit 0
fi

failed=0
for subject in ${subjects}; do
    skip=0
    for skipped in ${SKIP_SUBJECTS}; do
        if [ "${subject}" = "${skipped}" ]; then
            echo "[set-schema-compat] skip ${subject} (intentionally pinned)"
            skip=1
            break
        fi
    done
    if [ "${skip}" -eq 1 ]; then
        continue
    fi

    # PUT the compatibility level. ``-w '%{http_code}'`` prints the status code
    # so we can distinguish 200 (success) from anything else.
    response="$(curl -sS -o /tmp/sr_resp.$$ -w '%{http_code}' \
        -X PUT \
        -H 'Content-Type: application/vnd.schemaregistry.v1+json' \
        --data "{\"compatibility\":\"${COMPAT_LEVEL}\"}" \
        "${REGISTRY_URL}/config/${subject}")"
    if [ "${response}" = "200" ]; then
        echo "[set-schema-compat] ok ${subject} → ${COMPAT_LEVEL}"
    else
        echo "[set-schema-compat] FAILED ${subject} (HTTP ${response}): $(cat /tmp/sr_resp.$$)" >&2
        failed=$((failed + 1))
    fi
    rm -f /tmp/sr_resp.$$
done

if [ "${failed}" -gt 0 ]; then
    echo "[set-schema-compat] ${failed} subject(s) failed" >&2
    exit 1
fi

echo "[set-schema-compat] done"
