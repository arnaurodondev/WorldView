#!/usr/bin/env bash
#
# rebuild_service.sh — reliably ship code changes for a whole service FAMILY.
#
# WHY THIS EXISTS (the DEPLOY-STALENESS gotcha):
#   In infra/compose/docker-compose.yml, every variant of a service
#   (app + *-migrate + each *-consumer / *-worker / *-scheduler / *-dispatcher)
#   has its OWN `build:` block and therefore builds its OWN image
#   (worldview-<service-name>:latest). They all share one Dockerfile, but Docker
#   Compose tracks them as SEPARATE images.
#
#   Consequence: `docker compose build market-data` updates ONLY
#   worldview-market-data:latest. The migrate job, the OHLCV consumer, the
#   intraday-resampling consumer, etc. keep running their OLD images — so a code
#   change appears to "not deploy" until you rebuild every variant. This has
#   bitten us repeatedly (market-ingestion-migrate "Can't locate revision 0023";
#   market-data-intraday-resampling-consumer running the old resampler).
#
#   This script rebuilds AND recreates EVERY compose service in a family with a
#   single command, so a code change reliably lands in every container.
#
# USAGE:
#   scripts/rebuild_service.sh <family> [--cache] [--no-recreate] [--prod]
#
#   <family>        Service family prefix, e.g. market-data, market-ingestion,
#                   knowledge-graph, nlp-pipeline, content-store, content-ingestion,
#                   portfolio, alert, rag-chat. Also accepts a single standalone
#                   service (api-gateway, gliner-server, worldview-web,
#                   intelligence-migrations, synthetic-monitor).
#   --cache         Use Docker layer cache (faster; default is --no-cache for
#                   maximum reliability — never ship stale code again).
#   --no-recreate   Build only; do not (re)create/restart containers.
#   --prod          Operate on the prod compose stack instead of the dev stack.
#
# EXAMPLES:
#   scripts/rebuild_service.sh market-data            # no-cache build + recreate all 9 variants
#   scripts/rebuild_service.sh market-ingestion       # rebuilds the migrate job too
#   scripts/rebuild_service.sh knowledge-graph --cache
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$REPO_ROOT/infra/compose"

FAMILY="${1:-}"
if [[ -z "$FAMILY" || "$FAMILY" == "-"* ]]; then
  echo "ERROR: missing <family> argument." >&2
  echo "Usage: scripts/rebuild_service.sh <family> [--cache] [--no-recreate] [--prod]" >&2
  exit 2
fi
shift || true

USE_CACHE=0
RECREATE=1
PROD=0
for arg in "$@"; do
  case "$arg" in
    --cache)       USE_CACHE=1 ;;
    --no-recreate) RECREATE=0 ;;
    --prod)        PROD=1 ;;
    *) echo "ERROR: unknown flag '$arg'" >&2; exit 2 ;;
  esac
done

# Select the same compose file set the Makefile uses for dev vs prod, so the
# image names / project ("worldview") match what `make dev` / `make prod` boot.
if [[ "$PROD" -eq 1 ]]; then
  COMPOSE=(docker compose
    -f "$COMPOSE_DIR/docker-compose.yml"
    -f "$COMPOSE_DIR/docker-compose.prod.yml")
else
  COMPOSE=(docker compose
    -f "$COMPOSE_DIR/docker-compose.yml"
    -f "$COMPOSE_DIR/docker-compose.dev.yml"
    --profile infra)
fi

# Resolve the family to its concrete compose service list.
# A member is the family itself OR family + "-<suffix>". We match against the
# base compose file (single source of build truth — overlays add no build:
# blocks) to avoid env-file requirements that `compose config` imposes.
ALL_SERVICES="$(awk '/^  [a-zA-Z0-9_-]+:$/{svc=$1} /^    build:$/{print svc}' \
  "$COMPOSE_DIR/docker-compose.yml" | tr -d ':')"

SERVICES=()
while IFS= read -r svc; do
  [[ -z "$svc" ]] && continue
  if [[ "$svc" == "$FAMILY" || "$svc" == "$FAMILY-"* ]]; then
    SERVICES+=("$svc")
  fi
done <<< "$ALL_SERVICES"

if [[ "${#SERVICES[@]}" -eq 0 ]]; then
  echo "ERROR: no compose services match family '$FAMILY'." >&2
  echo "Known families/services:" >&2
  echo "$ALL_SERVICES" | sed 's/^/  - /' >&2
  exit 1
fi

echo "==> Family '$FAMILY' resolves to ${#SERVICES[@]} compose service(s):"
printf '      %s\n' "${SERVICES[@]}"

BUILD_FLAGS=()
if [[ "$USE_CACHE" -eq 0 ]]; then
  BUILD_FLAGS+=(--no-cache)
  echo "==> Building with --no-cache (reliable; pass --cache to use layer cache)."
else
  echo "==> Building with layer cache (--cache)."
fi

echo "==> Building images SEQUENTIALLY (one service at a time)..."
# CRITICAL: build each variant in its OWN `docker compose build` invocation, NOT
# all at once. Building a whole family (up to 15 services) in a single parallel
# BuildKit call crashes the BuildKit grpc frontend under memory pressure
# ("failed to solve: frontend grpc server closed unexpectedly") and silently
# leaves STALE images — which is exactly the deploy-staleness bug this script
# exists to prevent. Sequential builds keep peak memory low (the host has OOM'd
# during mass rebuilds) and surface any per-service failure immediately.
#
# NOTE: ${arr[@]+"${arr[@]}"} guards against `set -u` treating an EMPTY array as
# an unbound variable on bash 3.2 (the default on macOS). BUILD_FLAGS is empty
# whenever --cache is passed.
for svc in "${SERVICES[@]}"; do
  echo "    --> building $svc"
  "${COMPOSE[@]}" build ${BUILD_FLAGS[@]+"${BUILD_FLAGS[@]}"} "$svc"
done

if [[ "$RECREATE" -eq 1 ]]; then
  echo "==> Recreating containers (--force-recreate)..."
  "${COMPOSE[@]}" up -d --force-recreate --no-deps "${SERVICES[@]}"
  echo "==> Done. All ${#SERVICES[@]} variant(s) of '$FAMILY' are running the new image."
else
  echo "==> Build complete (--no-recreate: containers NOT restarted)."
fi
