#!/usr/bin/env bash
# Create all Kafka topics.
set -euo pipefail

KAFKA_BIN="/opt/kafka/bin"
BOOTSTRAP="kafka:29092"

echo "=== Creating Kafka topics ==="

TOPICS=(
    "portfolio.events.v1:3:1"
    "market.dataset.fetched:6:1"
    "market.instrument.created:3:1"
    "market.instrument.updated:3:1"
    "content.article.raw.v1:3:1"
    "content.article.stored.v1:6:1"
    "nlp.article.enriched.v1:6:1"
    "nlp.signal.detected.v1:3:1"
)

for TOPIC_SPEC in "${TOPICS[@]}"; do
    IFS=':' read -r TOPIC PARTITIONS REPLICATION <<< "$TOPIC_SPEC"
    echo "Creating topic: $TOPIC (partitions=$PARTITIONS, replication=$REPLICATION)"
    "$KAFKA_BIN/kafka-topics.sh" \
        --bootstrap-server "$BOOTSTRAP" \
        --create \
        --if-not-exists \
        --topic "$TOPIC" \
        --partitions "$PARTITIONS" \
        --replication-factor "$REPLICATION"
done

echo "=== Topic creation complete ==="
"$KAFKA_BIN/kafka-topics.sh" --bootstrap-server "$BOOTSTRAP" --list
