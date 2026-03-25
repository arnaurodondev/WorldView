#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="infra/compose/docker-compose.test.yml"
PROFILE="${1:-all}"
MAX_RETRIES="${MAX_RETRIES:-60}"
SLEEP_SECONDS="${SLEEP_SECONDS:-2}"

cd "$(dirname "$0")/.."

echo "Waiting for services in profile '$PROFILE' to become ready..."

wait_for() {
  local name="$1"
  local cmd="$2"
  local tries=0

  until eval "$cmd" >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [[ "$tries" -ge "$MAX_RETRIES" ]]; then
      echo "Timeout while waiting for $name"
      return 1
    fi
    sleep "$SLEEP_SECONDS"
  done

  echo "Ready: $name"
}

wait_for "Kafka" "docker compose -f $COMPOSE_FILE --profile $PROFILE exec -T kafka kafka-broker-api-versions --bootstrap-server localhost:9092"
wait_for "Schema Registry" "curl -fsS http://localhost:8081/subjects"

if docker compose -f "$COMPOSE_FILE" --profile "$PROFILE" ps --services | grep -q '^postgres$'; then
  wait_for "Postgres" "docker compose -f $COMPOSE_FILE --profile $PROFILE exec -T postgres pg_isready -U postgres"
fi

if docker compose -f "$COMPOSE_FILE" --profile "$PROFILE" ps --services | grep -q '^timescaledb$'; then
  wait_for "TimescaleDB" "docker compose -f $COMPOSE_FILE --profile $PROFILE exec -T timescaledb pg_isready -U postgres"
fi

if docker compose -f "$COMPOSE_FILE" --profile "$PROFILE" ps --services | grep -q '^minio$'; then
  wait_for "MinIO" "curl -fsS http://localhost:7480/minio/health/live"
fi

if docker compose -f "$COMPOSE_FILE" --profile "$PROFILE" ps --services | grep -q '^valkey$'; then
  wait_for "Valkey" "docker compose -f $COMPOSE_FILE --profile $PROFILE exec -T valkey valkey-cli ping | grep -q PONG"
fi

echo "All detected services are ready."
