#!/usr/bin/env bash
# Create MinIO buckets for the platform.
set -euo pipefail

echo "=== Setting up MinIO ==="

mc alias set local http://minio:9000 minioadmin minioadmin

BUCKETS=(
    market-data
    content-data
    intelligence-data
    rag-data
    market-bronze
    market-canonical
    worldview-bronze
    worldview-silver
    worldview
)

for BUCKET in "${BUCKETS[@]}"; do
    echo "Creating bucket: $BUCKET"
    mc mb --ignore-existing "local/$BUCKET"
done

# --- Lifecycle / retention (inode-exhaustion guard) ---------------------------
# The bronze buckets are the RAW landing zone: one object is written per fetch.
# MinIO's XL layout stores each object as its own directory tree, so object COUNT
# (not byte size) is what exhausts the volume's inodes. On 2026-07-16 the prod
# MinIO volume hit inode exhaustion at ~50% bytes because these buckets grew
# unbounded during the multi-year backfills.
#
# The root-cause firehose — the write-only Polymarket CLOB/trades/OI/events
# per-record archive — is now disabled at SOURCE (content-ingestion
# ``*ProviderSettings.bronze_archive_enabled=False``), so going forward almost no
# new polymarket-* objects are created. These per-prefix rules are therefore a
# belt-and-suspenders safety net: they expire any legacy/opt-in objects and any
# other bronze prefix, so a fresh provision can never re-accumulate silently.
#
# Because the firehose is off, the expiry windows can be modest/generous rather
# than the aggressive 1-day live band-aid — a few days of retention is plenty for
# re-fetchable raw. Bronze is always re-fetchable (canonical/silver/rag/*-data
# hold the durable promoted copies and are intentionally left untouched).
#
# Per-prefix days are overridable via env so operators can tune per environment.
# Prefixes match the adapter key layouts:
#   worldview-bronze/content-ingestion/polymarket-{clob,trades,oi,events}/  (firehose)
#   worldview-bronze/content-ingestion/{eodhd,sec_edgar}/                   (news/filings)
#   market-bronze/market-ingestion/raw/                                     (OHLCV/fundamentals)
POLYMARKET_EXPIRE_DAYS="${MINIO_POLYMARKET_EXPIRE_DAYS:-1}"
NEWS_EXPIRE_DAYS="${MINIO_NEWS_EXPIRE_DAYS:-3}"
MARKET_BRONZE_EXPIRE_DAYS="${MINIO_MARKET_BRONZE_EXPIRE_DAYS:-3}"
# Silver = the cleaned/extracted text bodies promoted from bronze. Same rationale
# as bronze: the bodies are RE-FETCHABLE (they can be re-derived from bronze or
# re-fetched from source), so a bounded window caps object/inode growth without
# risking durable data — the canonical/rag/*-data promoted copies are untouched.
# A slightly longer window than bronze (14d) since silver is one step closer to
# the durable copies. Env-overridable.
SILVER_EXPIRE_DAYS="${MINIO_SILVER_EXPIRE_DAYS:-14}"

add_expiry_rule() {
    # $1 = bucket/prefix path, $2 = expire-days. Idempotent enough for init:
    # a duplicate rule is harmless, so tolerate a non-zero exit.
    local target="$1" days="$2"
    echo "  expire-days=${days}: local/${target}"
    mc ilm rule add --expire-days "$days" "local/${target}" \
        || echo "    (lifecycle rule already present or unsupported — continuing)"
}

echo "=== Applying bronze lifecycle rules ==="
# Polymarket deeper-stream firehose prefixes — short window (writes now disabled).
for STREAM in polymarket-clob polymarket-trades polymarket-oi polymarket-events polymarket; do
    add_expiry_rule "worldview-bronze/content-ingestion/${STREAM}/" "$POLYMARKET_EXPIRE_DAYS"
done
# News + SEC filings raw — modest window (batched per fetch, lower object count).
for SRC in eodhd eodhd_ticker_news sec_edgar newsapi finnhub; do
    add_expiry_rule "worldview-bronze/content-ingestion/${SRC}/" "$NEWS_EXPIRE_DAYS"
done
# market-bronze: market-ingestion writes ONE object per fetch-task (a whole OHLCV
# series per object, NOT one-per-bar), so object count is bounded — but a
# multi-year backfill still accumulates, so give the whole bucket a generous rule.
add_expiry_rule "market-bronze" "$MARKET_BRONZE_EXPIRE_DAYS"
# Silver: cleaned text bodies (re-fetchable) — bounded window on the whole bucket.
add_expiry_rule "worldview-silver" "$SILVER_EXPIRE_DAYS"

echo "=== MinIO setup complete ==="
mc ls local
echo "=== Bronze + silver lifecycle rules ==="
for BUCKET in worldview-bronze market-bronze worldview-silver; do
    mc ilm rule ls "local/$BUCKET" || true
done
