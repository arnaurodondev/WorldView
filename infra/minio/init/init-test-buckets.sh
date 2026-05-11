#!/usr/bin/env bash
# Create MinIO buckets required for the market-ingestion and market-data test stacks.
# Runs as a one-shot init container via mc (MinIO Client).
set -euo pipefail

echo "=== Setting up MinIO test buckets ==="

mc alias set local http://minio:9000 minioadmin minioadmin

for BUCKET in market-ingestion market-bronze market-canonical market-data worldview-bronze worldview-silver worldview; do
    echo "Creating bucket: $BUCKET"
    mc mb --ignore-existing "local/$BUCKET"
done

echo "=== MinIO test bucket setup complete ==="
mc ls local
