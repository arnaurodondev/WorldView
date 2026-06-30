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

# CACHE_BUST defeats BuildKit's stale local-source snapshot (see
# docs/audits/2026-06-27-compose-build-stale-prompts.md and the matching
# `ARG CACHE_BUST` in services/rag-chat/Dockerfile). A value that changes with
# the working-tree state forces BuildKit to re-snapshot the local build context,
# so an edited shared lib (libs/prompts, libs/contracts, …) can never be served
# from a deduped old snapshot. Plain `docker build` without this arg keeps its
# default behaviour (the ARG default is `unset`). Dockerfiles that do not declare
# the ARG simply ignore it.
CACHE_BUST_VALUE="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo nogit)-$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null | md5 2>/dev/null || git -C "$REPO_ROOT" status --porcelain 2>/dev/null | md5sum 2>/dev/null | cut -d' ' -f1 || date +%s)"
BUILD_FLAGS+=(--build-arg "CACHE_BUST=${CACHE_BUST_VALUE}")

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

# ── Post-build staleness guard ────────────────────────────────────────────────
# Belt-and-suspenders for the BuildKit stale-local-source bug
# (docs/audits/2026-06-27-compose-build-stale-prompts.md): even with the
# CACHE_BUST arg above, assert the FRESHLY BUILT image actually contains the
# current on-disk libs/prompts version. We grep the version string in the image
# and compare it to the source tree; a mismatch means a stale shared lib was
# shipped — fail loudly instead of silently deploying old code.
#
# Only applies to images that bundle libs/prompts (every service does today, but
# we resolve the image name from compose so a future no-prompts service is a
# no-op skip rather than a false failure).
ondisk_prompts_ver="$(grep -m1 -oE 'version="[^"]+"' \
  "$REPO_ROOT/libs/prompts/src/prompts/chat/synthesis.py" 2>/dev/null \
  | sed -E 's/version="([^"]+)"/\1/' || true)"
if [[ -n "$ondisk_prompts_ver" ]]; then
  echo "==> Verifying built image(s) carry libs/prompts synthesis version '$ondisk_prompts_ver'..."
  for svc in "${SERVICES[@]}"; do
    # Compose names each built image worldview-<service>:latest (project
    # "worldview"). `compose config --images <svc>` is unreliable across Compose
    # versions (some ignore the service filter and list every image), so we use
    # the conventional tag directly — it matches what the build loop just wrote.
    img="worldview-${svc}:latest"
    # The lib is installed into the venv site-packages; resolve via importlib so
    # we don't hardcode the python minor version in the path.
    img_ver="$(docker run --rm --entrypoint sh "$img" -c \
      'python -c "import prompts.chat.synthesis as s; print(s.SYNTHESIS_SYSTEM_PROMPT.version)"' \
      2>/dev/null | tr -d '[:space:]' || true)"
    if [[ -z "$img_ver" ]]; then
      echo "    (skip) $svc ($img): libs/prompts not importable — assuming not bundled."
      continue
    fi
    if [[ "$img_ver" != "$ondisk_prompts_ver" ]]; then
      echo "ERROR: STALE BUILD — $svc image '$img' ships libs/prompts synthesis" >&2
      echo "       version '$img_ver' but on-disk source is '$ondisk_prompts_ver'." >&2
      echo "       BuildKit served a stale local-source snapshot. Fix: clear it with" >&2
      echo "       'docker builder prune -f' and re-run this script." >&2
      exit 3
    fi
    echo "    OK   $svc ($img): libs/prompts == $img_ver"
  done
fi

if [[ "$RECREATE" -eq 1 ]]; then
  echo "==> Recreating containers (--force-recreate)..."
  "${COMPOSE[@]}" up -d --force-recreate --no-deps "${SERVICES[@]}"
  echo "==> Done. All ${#SERVICES[@]} variant(s) of '$FAMILY' are running the new image."
else
  echo "==> Build complete (--no-recreate: containers NOT restarted)."
fi
