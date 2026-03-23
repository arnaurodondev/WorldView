"""Avro schema definitions for content ingestion events."""

from __future__ import annotations

ARTICLE_RAW_V1_SCHEMA: dict = {
    "type": "record",
    "name": "ArticleRawV1",
    "namespace": "com.worldview.content",
    "fields": [
        {"name": "article_id", "type": "string"},
        {"name": "source_type", "type": "string"},
        {"name": "url", "type": "string"},
        {"name": "url_hash", "type": "string"},
        {"name": "minio_key", "type": "string"},
        {"name": "fetched_at", "type": "string"},
        {"name": "byte_size", "type": "int"},
        # Backfill extension fields (schema v1.1 additions — backward-compatible defaults)
        {"name": "published_at", "type": ["null", "string"], "default": None},
        {"name": "is_backfill", "type": "boolean", "default": False},
    ],
}
