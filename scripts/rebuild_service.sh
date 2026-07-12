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
#   scripts/rebuild_service.sh <family> [--cache] [--no-recreate] [--prod] [--parallel]
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
#   --parallel      Build up to COMPOSE_PARALLEL_LIMIT (default 3, capped at 3)
#                   services concurrently instead of strictly one-at-a-time.
#                   Opt-in: default stays serial (see the build loop for why).
#
# ENV:
#   COMPOSE_PARALLEL_LIMIT   Max concurrent builds when --parallel is set
#                            (default 3; clamped to the 1..3 safe range).
#
# POST-RECREATE VERIFICATION (always on when recreating):
#   After `up -d --force-recreate`, the script ASSERTS, per compose service:
#     1) the running container's image ID == the freshly built
#        worldview-<svc>:latest image ID  (catches recreate-vs-rebuild staleness);
#     2) every *-migrate sidecar reached exited(0) (catches the
#        Created-but-never-started / crashed-migration class).
#   Any mismatch fails the script loudly (exit 4).
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
PARALLEL=0
for arg in "$@"; do
  case "$arg" in
    --cache)       USE_CACHE=1 ;;
    --no-recreate) RECREATE=0 ;;
    --prod)        PROD=1 ;;
    --parallel)    PARALLEL=1 ;;
    *) echo "ERROR: unknown flag '$arg'" >&2; exit 2 ;;
  esac
done

# Clamp the concurrency cap to the 1..3 safe range (see the build loop rationale).
PARALLEL_LIMIT="${COMPOSE_PARALLEL_LIMIT:-3}"
if ! [[ "$PARALLEL_LIMIT" =~ ^[0-9]+$ ]] || [[ "$PARALLEL_LIMIT" -lt 1 ]]; then
  PARALLEL_LIMIT=1
elif [[ "$PARALLEL_LIMIT" -gt 3 ]]; then
  PARALLEL_LIMIT=3
fi

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

# ── FULL-FAMILY recreate set (the stale-image fix, 2026-07-12) ────────────────
# CRITICAL: only the family BASE service carries a `build:` block; every other
# variant (*-migrate / *-consumer / *-worker / *-scheduler / *-dispatcher /
# *-detector / *-poller) is defined with `image: worldview-<family>:latest` and
# NO build block. The old SERVICES list (build-blocks only) therefore recreated
# ONLY the base service, leaving all consumers/workers/dispatchers pinned to the
# OLD image after a rebuild — the exact deploy-staleness bug this script claims
# to prevent (observed live: alert-dispatcher/rule-poller/watchlist-consumer
# running a stale image hash while worldview-alert:latest had moved on).
#
# We therefore parse EVERY compose service (not just buildable ones) matching
# the family prefix, together with the image tag it runs, and force-recreate the
# whole set onto the freshly built shared image. SERVICES (build-blocks only) is
# still used for the BUILD loop — you can only `compose build` a service that
# has a build: block.
#
# Parsing: walk the `services:` section (stop at the top-level `volumes:` key)
# tracking the current 2-space-indented service key; for each `image:` under it
# emit "<svc> <image>". Every family member declares an image, so this yields a
# svc→image map we filter by family prefix.
FAMILY_MAP="$(awk '
  /^volumes:/ { exit }
  /^  [a-zA-Z0-9_-]+:$/ { svc=substr($1, 1, length($1)-1); next }
  /^    image:/ { if (svc != "") print svc, $2 }
' "$COMPOSE_DIR/docker-compose.yml")"

RECREATE_SERVICES=()
declare -a RECREATE_IMAGES=()   # parallel array: image tag per recreate service
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  svc="${line%% *}"
  img="${line##* }"
  if [[ "$svc" == "$FAMILY" || "$svc" == "$FAMILY-"* ]]; then
    RECREATE_SERVICES+=("$svc")
    RECREATE_IMAGES+=("$img")
  fi
done <<< "$FAMILY_MAP"

if [[ "${#SERVICES[@]}" -eq 0 ]]; then
  echo "ERROR: no compose services match family '$FAMILY'." >&2
  echo "Known families/services:" >&2
  while IFS= read -r _svc; do [[ -n "$_svc" ]] && echo "  - $_svc" >&2; done <<< "$ALL_SERVICES"
  exit 1
fi

echo "==> Family '$FAMILY' resolves to ${#SERVICES[@]} buildable service(s):"
printf '      %s\n' "${SERVICES[@]}"
echo "==> Family '$FAMILY' resolves to ${#RECREATE_SERVICES[@]} runnable variant(s) to recreate:"
printf '      %s\n' "${RECREATE_SERVICES[@]}"

BUILD_FLAGS=()
if [[ "$USE_CACHE" -eq 0 ]]; then
  BUILD_FLAGS+=(--no-cache)
  echo "==> Building with --no-cache (reliable; pass --cache to use layer cache)."
else
  echo "==> Building with layer cache (--cache)."
fi

# NOTE (2026-07-05): the former `--build-arg CACHE_BUST=<tree-state>` was REMOVED.
# The build/deploy audit concluded it was a workaround for the old `.next`/context
# bloat (since fixed), NOT a live BuildKit defect: CI never passed it and never
# shipped stale (fresh clone per run). The real staleness guard is the POST-BUILD
# prompt-version assertion below, which we keep. A leftover default
# `ARG CACHE_BUST=unset` in a Dockerfile is harmless (unused build args are just
# ignored).

# CRITICAL (default = strictly serial): build each variant in its OWN
# `docker compose build` invocation, NOT all at once. Building a whole family
# (up to 15 services) in a single parallel BuildKit call crashes the BuildKit
# grpc frontend under memory pressure ("failed to solve: frontend grpc server
# closed unexpectedly") and silently leaves STALE images — the very
# deploy-staleness bug this script exists to prevent. Strict-serial keeps peak
# memory low (the host has OOM'd during mass rebuilds) and surfaces any
# per-service failure immediately.
#
# --parallel relaxes this to a SMALL bounded fan-out (COMPOSE_PARALLEL_LIMIT,
# clamped 1..3). A cap of 2–3 is safe: it is nowhere near the "build everything
# at once" pressure that OOMs the host / crashes the grpc frontend, and it
# roughly halves wall-clock on multi-variant families. We also `docker pull
# docker/dockerfile:1` FIRST so concurrent builds don't race to fetch the
# Dockerfile frontend image (that race is the "frontend grpc server closed
# unexpectedly" crash seen on the worldview-web build).
#
# NOTE: ${arr[@]+"${arr[@]}"} guards against `set -u` treating an EMPTY array as
# an unbound variable on bash 3.2 (the default on macOS). BUILD_FLAGS is empty
# whenever --cache is passed.
build_one() {
  # Build a single compose service; on failure print its captured log.
  local svc="$1" logf="$2"
  if ! "${COMPOSE[@]}" build ${BUILD_FLAGS[@]+"${BUILD_FLAGS[@]}"} "$svc" >"$logf" 2>&1; then
    echo "ERROR: build failed for $svc — log follows:" >&2
    cat "$logf" >&2
    return 1
  fi
  return 0
}

if [[ "$PARALLEL" -eq 1 && "${#SERVICES[@]}" -gt 1 ]]; then
  echo "==> Building images with bounded parallelism (limit=$PARALLEL_LIMIT)..."
  # Pre-pull the Dockerfile frontend so concurrent builds don't race to fetch it.
  echo "    --> pulling docker/dockerfile:1 (frontend image, avoids grpc race)"
  docker pull docker/dockerfile:1 >/dev/null 2>&1 || \
    echo "    (warn) could not pre-pull docker/dockerfile:1; continuing"

  # Batched fan-out: launch up to PARALLEL_LIMIT builds, wait for the batch,
  # repeat. Batching (vs. a sliding window) stays portable to bash 3.2, which
  # lacks `wait -n`. Per-service logs avoid interleaved output.
  build_fail=0
  pids=()
  metas=()   # parallel array: "svc:::logf" for each pid
  flush_batch() {
    local i pid meta svc logf rc
    for i in "${!pids[@]}"; do
      pid="${pids[$i]}"; meta="${metas[$i]}"
      svc="${meta%%:::*}"; logf="${meta##*:::}"
      if wait "$pid"; then
        rc=0
      else
        rc=1
      fi
      if [[ "$rc" -ne 0 ]]; then
        echo "ERROR: build failed for $svc — log:" >&2
        cat "$logf" >&2
        build_fail=1
      else
        echo "    OK   built $svc"
      fi
      rm -f "$logf"
    done
    pids=()
    metas=()
  }
  for svc in "${SERVICES[@]}"; do
    logf="$(mktemp)"
    echo "    --> building $svc (background)"
    build_one "$svc" "$logf" &
    pids+=("$!")
    metas+=("$svc:::$logf")
    if [[ "${#pids[@]}" -ge "$PARALLEL_LIMIT" ]]; then
      flush_batch
    fi
  done
  flush_batch
  if [[ "$build_fail" -ne 0 ]]; then
    echo "ERROR: one or more parallel builds failed (see logs above)." >&2
    exit 3
  fi
else
  echo "==> Building images SEQUENTIALLY (one service at a time)..."
  for svc in "${SERVICES[@]}"; do
    echo "    --> building $svc"
    logf="$(mktemp)"
    if ! build_one "$svc" "$logf"; then
      rm -f "$logf"
      exit 3
    fi
    cat "$logf"
    rm -f "$logf"
  done
fi

# ── Post-build staleness guard ────────────────────────────────────────────────
# Belt-and-suspenders for the BuildKit stale-local-source bug
# (docs/audits/2026-06-27-compose-build-stale-prompts.md): assert the FRESHLY
# BUILT image actually contains the current on-disk libs/prompts version. This
# is now the PRIMARY staleness guard (replacing the removed CACHE_BUST arg). We
# grep the version string in the image
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
  echo "==> Recreating ALL ${#RECREATE_SERVICES[@]} family variant(s) (--force-recreate)..."
  # Recreate the FULL family (base + every consumer/worker/dispatcher/migrate),
  # not just buildable services — otherwise variants stay on the OLD image.
  "${COMPOSE[@]}" up -d --force-recreate --no-deps "${RECREATE_SERVICES[@]}"

  # ── Post-recreate deploy verification ──────────────────────────────────────
  # Two failure classes this catches:
  #   (1) recreate-vs-rebuild staleness — the container came up on an OLD image
  #       (e.g. a variant that wasn't recreated, or compose reused a cached
  #       container). We assert the RUNNING container's image ID equals the
  #       freshly built worldview-<svc>:latest image ID.
  #   (2) Created-but-never-started / crashed migrations — a *-migrate sidecar
  #       runs to completion; if it never reached exited(0) the schema is not
  #       applied and dependent services will crashloop. We assert exited(0).
  echo "==> Verifying ALL recreated variants run the freshly built image..."
  verify_fail=0
  for idx in "${!RECREATE_SERVICES[@]}"; do
    svc="${RECREATE_SERVICES[$idx]}"
    # Variants share the family base image (worldview-<family>:latest); resolve
    # each service's declared image from the compose map so we verify variants
    # against the SHARED freshly built image, not a per-variant tag that doesn't
    # exist.
    ref_img="${RECREATE_IMAGES[$idx]}"
    built_id="$(docker image inspect --format '{{.Id}}' "$ref_img" 2>/dev/null || true)"
    if [[ -z "$built_id" ]]; then
      echo "    (skip) $svc: image '$ref_img' not found locally."
      continue
    fi

    # Resolve the running container id(s) for this compose service. A service
    # normally maps to exactly one container; loop to be safe.
    cids="$("${COMPOSE[@]}" ps -q "$svc" 2>/dev/null || true)"

    is_migrate=0
    case "$svc" in *-migrate) is_migrate=1 ;; esac

    if [[ -z "$cids" ]]; then
      if [[ "$is_migrate" -eq 1 ]]; then
        # A migrate job may already have exited; look it up including stopped.
        cids="$(docker ps -aq --filter "name=${svc}" 2>/dev/null || true)"
        if [[ -z "$cids" ]]; then
          echo "ERROR: migrate sidecar '$svc' has NO container (never started)." >&2
          verify_fail=1
        fi
      else
        echo "ERROR: service '$svc' has NO running container after recreate." >&2
        verify_fail=1
      fi
    fi

    while IFS= read -r cid; do
      [[ -z "$cid" ]] && continue
      run_id="$(docker inspect --format '{{.Image}}' "$cid" 2>/dev/null || true)"
      status="$(docker inspect --format '{{.State.Status}}' "$cid" 2>/dev/null || true)"
      exitcode="$(docker inspect --format '{{.State.ExitCode}}' "$cid" 2>/dev/null || true)"

      # Image-digest match (both are sha256:... image IDs from the same daemon).
      if [[ "$run_id" != "$built_id" ]]; then
        echo "ERROR: STALE CONTAINER — $svc ($cid) runs image '$run_id'" >&2
        echo "       but freshly built '$ref_img' is '$built_id'." >&2
        verify_fail=1
      fi

      if [[ "$is_migrate" -eq 1 ]]; then
        # Migrate must have run to completion successfully.
        if [[ "$status" != "exited" || "$exitcode" != "0" ]]; then
          echo "ERROR: migrate sidecar '$svc' ($cid) is status='$status'" >&2
          echo "       exit=$exitcode — expected exited(0). Schema NOT applied." >&2
          verify_fail=1
        else
          echo "    OK   $svc: migrate exited(0) on fresh image."
        fi
      else
        # Long-running service must actually be up (not restarting/exited).
        if [[ "$status" != "running" ]]; then
          echo "ERROR: service '$svc' ($cid) is status='$status' — not running." >&2
          verify_fail=1
        elif [[ "$run_id" == "$built_id" ]]; then
          echo "    OK   $svc: running on freshly built image."
        fi
      fi
    done <<< "$cids"
  done

  if [[ "$verify_fail" -ne 0 ]]; then
    echo "ERROR: deploy verification FAILED — one or more containers are stale" >&2
    echo "       or a migration did not complete. See errors above." >&2
    exit 4
  fi

  echo "==> Done. All ${#RECREATE_SERVICES[@]} variant(s) of '$FAMILY' verified on the new image."
else
  echo "==> Build complete (--no-recreate: containers NOT restarted)."
fi
