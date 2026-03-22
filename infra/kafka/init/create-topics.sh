#!/usr/bin/env bash
# Create all Kafka topics.
set -euo pipefail

BOOTSTRAP="kafka:29092"

if command -v kafka-topics >/dev/null 2>&1; then
    KAFKA_TOPICS_CMD="kafka-topics"
elif [[ -x "/usr/bin/kafka-topics" ]]; then
    KAFKA_TOPICS_CMD="/usr/bin/kafka-topics"
elif [[ -x "/opt/kafka/bin/kafka-topics.sh" ]]; then
    KAFKA_TOPICS_CMD="/opt/kafka/bin/kafka-topics.sh"
else
    echo "ERROR: kafka-topics CLI not found in container"
    exit 127
fi

echo "=== Creating Kafka topics ==="

TOPICS=(
    "portfolio.events.v1:3:1"
    "portfolio.watchlist.updated.v1:3:1"
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
    "$KAFKA_TOPICS_CMD" \
        --bootstrap-server "$BOOTSTRAP" \
        --create \
        --if-not-exists \
        --topic "$TOPIC" \
        --partitions "$PARTITIONS" \
        --replication-factor "$REPLICATION"
done

echo "=== Topic creation complete ==="
"$KAFKA_TOPICS_CMD" --bootstrap-server "$BOOTSTRAP" --list
