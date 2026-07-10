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

if command -v kafka-configs >/dev/null 2>&1; then
    KAFKA_CONFIGS_CMD="kafka-configs"
elif [[ -x "/usr/bin/kafka-configs" ]]; then
    KAFKA_CONFIGS_CMD="/usr/bin/kafka-configs"
elif [[ -x "/opt/kafka/bin/kafka-configs.sh" ]]; then
    KAFKA_CONFIGS_CMD="/opt/kafka/bin/kafka-configs.sh"
else
    echo "ERROR: kafka-configs CLI not found in container"
    exit 127
fi

echo "=== Creating Kafka topics ==="

# ── Time-retention topics ─────────────────────────────────────────────────────
# Format: "topic:partitions:replication-factor"
# PLAN-0113 FR-1 (dev partition reduction): the single-node KRaft dev broker does
# not benefit from PRD §7's multi-broker production sizing. Dev declares 3
# partitions for the genuinely-parallel pipeline topics (content.article.raw.v1,
# content.article.stored.v1, nlp.article.enriched.v1, nlp.signal.detected.v1) and
# 1 partition for every other app topic (incl. all DLQs and the compacted
# entity.dirtied.v1 created below). This keeps total dev app partitions <= 40.
# The topic NAME set here MUST match the prod provisioning set in
# worldview-gitops apps/infra-kafka.yaml (FR-3 parity). Do NOT change RF.
TOPICS=(
    "portfolio.events.v1:1:1"
    "portfolio.watchlist.updated.v1:1:1"
    "market.dataset.fetched:1:1"
    "market.instrument.created:1:1"
    "market.instrument.updated:1:1"
    "market.instrument.discovered.v1:1:1"
    "content.article.raw.v1:3:1"
    "content.article.stored.v1:3:1"
    "nlp.article.enriched.v1:3:1"
    "nlp.signal.detected.v1:3:1"
    "graph.state.changed.v1:1:1"
    "intelligence.contradiction.v1:1:1"
    "relation.type.proposed.v1:1:1"
    "entity.canonical.created.v1:1:1"
    "entity.refresh.v1:1:1"
    "alert.delivered.v1:1:1"
    "market.prediction.v1:1:1"
    # PLAN-0056: deeper-stream + derived prediction topics (schemas exist in
    # infra/kafka/schemas but were never provisioned here — consumers logged
    # UNKNOWN_TOPIC_OR_PART and the alert IntelligenceConsumer went unhealthy
    # because market.prediction.signal.v1 was missing).
    "market.prediction.event.v1:1:1"
    "market.prediction.history.v1:3:1"
    "market.prediction.trade.v1:3:1"
    "market.prediction.oi.v1:1:1"
    "market.prediction.move.v1:1:1"
    "market.prediction.signal.v1:1:1"
    "kg.dead-letter.v1:1:1"
    "alert.dead-letter.v1:1:1"
    "nlp.dead-letter.v1:1:1"
    "content.dead-letter.v1:1:1"
    "market.dead-letter.v1:1:1"
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

# ── Compacted topic (log compaction, NOT time-retention) ─────────────────────
# entity.dirtied.v1: key = entity_id.
# After compaction, only the latest message per entity_id is retained.
# S7 async workers treat each message as "refresh entity X" — NOT a historical
# event sequence. Never consume this topic expecting a complete changelog.
echo "Creating compacted topic: entity.dirtied.v1"
"$KAFKA_TOPICS_CMD" \
    --bootstrap-server "$BOOTSTRAP" \
    --create \
    --if-not-exists \
    --topic entity.dirtied.v1 \
    --partitions 1 \
    --replication-factor 1 \
    --config cleanup.policy=compact \
    --config min.cleanable.dirty.ratio=0.01 \
    --config segment.ms=3600000

# ── Custom retention configuration ────────────────────────────────────────────
# 14-day retention: signal and graph change topics (operational data, high volume)
echo "Setting 14-day retention on nlp.signal.detected.v1"
"$KAFKA_CONFIGS_CMD" --bootstrap-server "$BOOTSTRAP" --alter \
    --entity-type topics \
    --entity-name nlp.signal.detected.v1 \
    --add-config retention.ms=1209600000

echo "Setting 14-day retention on graph.state.changed.v1"
"$KAFKA_CONFIGS_CMD" --bootstrap-server "$BOOTSTRAP" --alter \
    --entity-type topics \
    --entity-name graph.state.changed.v1 \
    --add-config retention.ms=1209600000

# 30-day retention: contradiction and relation type (lower volume; longer audit window)
echo "Setting 30-day retention on intelligence.contradiction.v1"
"$KAFKA_CONFIGS_CMD" --bootstrap-server "$BOOTSTRAP" --alter \
    --entity-type topics \
    --entity-name intelligence.contradiction.v1 \
    --add-config retention.ms=2592000000

echo "Setting 30-day retention on relation.type.proposed.v1"
"$KAFKA_CONFIGS_CMD" --bootstrap-server "$BOOTSTRAP" --alter \
    --entity-type topics \
    --entity-name relation.type.proposed.v1 \
    --add-config retention.ms=2592000000

echo "Setting 30-day retention on market.prediction.v1"
"$KAFKA_CONFIGS_CMD" --bootstrap-server "$BOOTSTRAP" --alter \
    --entity-type topics \
    --entity-name market.prediction.v1 \
    --add-config retention.ms=2592000000

# 30-day retention: primary pipeline topics — services may be down for extended
# maintenance windows; 7-day Kafka default is insufficient to avoid silent
# message loss beyond the retention window.
echo "Setting 30-day retention on market.dataset.fetched"
"$KAFKA_CONFIGS_CMD" --bootstrap-server "$BOOTSTRAP" --alter \
    --entity-type topics \
    --entity-name market.dataset.fetched \
    --add-config retention.ms=2592000000

echo "Setting 30-day retention on content.article.stored.v1"
"$KAFKA_CONFIGS_CMD" --bootstrap-server "$BOOTSTRAP" --alter \
    --entity-type topics \
    --entity-name content.article.stored.v1 \
    --add-config retention.ms=2592000000

echo "Setting 30-day retention on nlp.article.enriched.v1"
"$KAFKA_CONFIGS_CMD" --bootstrap-server "$BOOTSTRAP" --alter \
    --entity-type topics \
    --entity-name nlp.article.enriched.v1 \
    --add-config retention.ms=2592000000

echo "Setting 30-day retention on content.article.raw.v1"
"$KAFKA_CONFIGS_CMD" --bootstrap-server "$BOOTSTRAP" --alter \
    --entity-type topics \
    --entity-name content.article.raw.v1 \
    --add-config retention.ms=2592000000

# ── Verification ──────────────────────────────────────────────────────────────
echo "All topics created. Current topic list:"
"$KAFKA_TOPICS_CMD" --bootstrap-server "$BOOTSTRAP" --list
