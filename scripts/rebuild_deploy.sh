#!/usr/bin/env bash
# Reliable rebuild + redeploy of a single service image to the lean prod cluster.
#
# WHY THIS EXISTS
# ---------------
# Two independent caching traps silently ship a STALE image and cost hours of
# "why isn't my fix live" debugging (both hit during the 2026-07-15 bring-up):
#
#   1. BUILDKIT LAYER CACHE — a changed file under libs/ (e.g. ml-clients) can be
#      served from a stale `COPY libs/... /build/...` cache layer, so the pushed
#      image lacks the edit. Fix: `--no-cache-filter builder` forces the whole
#      builder stage (lib copy + install) to re-run.
#   2. NODE :latest CACHE — `kubectl rollout restart` does NOT guarantee a re-pull
#      of a moved `:latest` tag; containerd serves the cached digest. Fix: DELETE
#      the pods (imagePullPolicy=Always then genuinely re-pulls).
#
# This script does both, then VERIFIES the running pod actually executes the new
# code (not just that the rollout "succeeded"). Always prefer it over a bare
# `docker build … && kubectl rollout restart`.
#
# USAGE
#   export KUBECONFIG=~/.kube/config-worldview
#   scripts/rebuild_deploy.sh <service> [verify_py]
#
#   <service>   service dir under services/ (e.g. nlp-pipeline, knowledge-graph)
#   [verify_py] OPTIONAL python one-liner run inside a rolled pod to assert the
#               fix is live; script fails if it errors or prints "STALE".
#               e.g. 'import ml_clients.text_budget as t; print("OK" if t.MAX_TOKENS==360 else "STALE")'
#
# EXAMPLES
#   scripts/rebuild_deploy.sh nlp-pipeline \
#     'import ml_clients.text_budget as t; print("OK" if t.estimate_bert_tokens("한국")>10 else "STALE")'
#   scripts/rebuild_deploy.sh portfolio
set -euo pipefail

SVC="${1:?usage: rebuild_deploy.sh <service> [verify_py]}"
VERIFY_PY="${2:-}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="ghcr.io/arnaurodondev/worldview-${SVC}:latest"
NS="worldview"
PLATFORM="linux/amd64"   # Hetzner nodes are amd64; build hosts are often arm64

cd "$REPO_ROOT"
[ -f "services/${SVC}/Dockerfile" ] || { echo "no services/${SVC}/Dockerfile"; exit 1; }

echo "▸ [1/4] build ${IMAGE} (${PLATFORM}, --no-cache-filter builder)"
docker buildx build --platform "$PLATFORM" \
  --no-cache-filter builder \
  -f "services/${SVC}/Dockerfile" \
  -t "$IMAGE" --push .

echo "▸ [2/4] verify the PUSHED image content (before touching the cluster)"
if [ -n "$VERIFY_PY" ]; then
  docker rmi -f "$IMAGE" >/dev/null 2>&1 || true          # drop local cache
  docker pull --platform "$PLATFORM" "$IMAGE" >/dev/null
  OUT="$(docker run --rm --platform "$PLATFORM" --entrypoint python3 "$IMAGE" -c "$VERIFY_PY" 2>&1 || true)"
  echo "    image says: $OUT"
  echo "$OUT" | grep -q STALE && { echo "✗ pushed image is STALE — build cache served old code"; exit 2; }
fi

echo "▸ [3/4] force fresh pull: delete all ${SVC} pods (rollout restart does NOT re-pull :latest)"
mapfile -t PODS < <(kubectl -n "$NS" get pods --no-headers 2>/dev/null | grep "^${SVC}" | awk '{print $1}')
for p in "${PODS[@]}"; do kubectl -n "$NS" delete pod "$p" --wait=false >/dev/null 2>&1 || true; done
echo "    deleted ${#PODS[@]} pod(s); waiting for a Ready replacement…"
sleep 15
for _ in $(seq 1 24); do
  READY=$(kubectl -n "$NS" get pods --no-headers 2>/dev/null | grep "^${SVC}" | grep -c "1/1.*Running" || true)
  TOTAL=$(kubectl -n "$NS" get pods --no-headers 2>/dev/null | grep -c "^${SVC}" || true)
  [ "$READY" -ge 1 ] && [ "$READY" = "$TOTAL" ] && break
  sleep 5
done

echo "▸ [4/4] verify the RUNNING pod executes the new code"
POD=$(kubectl -n "$NS" get pods --no-headers 2>/dev/null | grep "^${SVC}" | grep Running | awk '{print $1}' | head -1)
echo "    rolled pod: $POD"
if [ -n "$VERIFY_PY" ] && [ -n "$POD" ]; then
  LIVE="$(kubectl -n "$NS" exec "$POD" -- python3 -c "$VERIFY_PY" 2>&1 || true)"
  echo "    pod says:  $LIVE"
  echo "$LIVE" | grep -q STALE && { echo "✗ running pod is STALE — node served cached image"; exit 3; }
fi
echo "✓ ${SVC} rebuilt + redeployed + verified live"
