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
)

for BUCKET in "${BUCKETS[@]}"; do
    echo "Creating bucket: $BUCKET"
    mc mb --ignore-existing "local/$BUCKET"
done

echo "=== MinIO setup complete ==="
mc ls local
