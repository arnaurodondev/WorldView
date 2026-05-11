#!/usr/bin/env bash
# scripts/test-docker-builds.sh — Build all Docker images locally to catch Dockerfile errors.
#
# Run before deploying to Hetzner or after editing Dockerfiles or shared libs.
# Uses BuildKit for layer caching.
#
# Usage:
#   ./scripts/test-docker-builds.sh [--service <name>] [--push] [--tag <tag>]
#
# Options:
#   --service <name>   Build only one service (e.g. portfolio)
#   --push             Also push to ghcr.io/<GITHUB_USER>/worldview-<service>:<tag>
#   --tag <tag>        Image tag (default: test)
#   --no-cache         Force rebuild without layer cache

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

TARGET_SERVICE=""
PUSH=false
TAG="test"
NO_CACHE=false

SERVICES=(
    portfolio
    market-ingestion
    market-data
    content-ingestion
    content-store
    nlp-pipeline
    knowledge-graph
    rag-chat
    api-gateway
    alert
    intelligence-migrations
)

usage() {
    cat <<'EOF'
Usage: ./scripts/test-docker-builds.sh [options]

Options:
  --service <name>    Build only this service
  --push              Push to ghcr.io after build (requires GITHUB_USER env var)
  --tag <tag>         Image tag (default: test)
  --no-cache          Disable BuildKit layer cache
  -h, --help          Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --service) TARGET_SERVICE="$2"; shift 2 ;;
        --push)    PUSH=true; shift ;;
        --tag)     TAG="$2"; shift 2 ;;
        --no-cache) NO_CACHE=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1"; usage; exit 2 ;;
    esac
done

cd "$ROOT_DIR"

export DOCKER_BUILDKIT=1

BUILD_ARGS=()
if $NO_CACHE; then
    BUILD_ARGS+=("--no-cache")
fi

PASS=0
FAIL=0
FAILED_SERVICES=()

build_service() {
    local svc="$1"
    local dockerfile="services/$svc/Dockerfile"

    if [[ ! -f "$dockerfile" ]]; then
        echo "  SKIP: $svc (no Dockerfile at $dockerfile)"
        return 0
    fi

    echo ""
    echo "Building $svc..."
    local image="worldview-$svc:$TAG"

    if docker build \
        "${BUILD_ARGS[@]}" \
        --file "$dockerfile" \
        --tag "$image" \
        --build-arg BUILDKIT_INLINE_CACHE=1 \
        . 2>&1; then
        echo "  OK: $image"
        ((PASS++)) || true

        if $PUSH; then
            local remote="ghcr.io/${GITHUB_USER:-$(git config user.email | cut -d@ -f1)}/worldview-$svc:$TAG"
            echo "  Pushing to $remote..."
            docker tag "$image" "$remote"
            docker push "$remote"
        fi
    else
        echo "  FAIL: $svc"
        ((FAIL++)) || true
        FAILED_SERVICES+=("$svc")
    fi
}

build_postgres() {
    echo ""
    echo "Building postgres (TimescaleDB + Apache AGE)..."
    local image="worldview-postgres:$TAG"

    if docker build \
        "${BUILD_ARGS[@]}" \
        --file infra/postgres/Dockerfile \
        --tag "$image" \
        infra/postgres/ 2>&1; then
        echo "  OK: $image"
        ((PASS++)) || true
    else
        echo "  FAIL: postgres"
        ((FAIL++)) || true
        FAILED_SERVICES+=("postgres")
    fi
}

echo "========================================"
echo "  worldview Docker build smoke tests"
echo "  Tag: $TAG | Push: $PUSH"
echo "========================================"

if [[ -n "$TARGET_SERVICE" ]]; then
    if [[ "$TARGET_SERVICE" == "postgres" ]]; then
        build_postgres
    else
        build_service "$TARGET_SERVICE"
    fi
else
    for svc in "${SERVICES[@]}"; do
        build_service "$svc"
    done
    build_postgres
fi

echo ""
echo "========================================"
echo "  Results: $PASS OK, $FAIL FAIL"
if [[ ${#FAILED_SERVICES[@]} -gt 0 ]]; then
    echo "  Failed: ${FAILED_SERVICES[*]}"
fi
echo "========================================"

[[ $FAIL -eq 0 ]] || exit 1
