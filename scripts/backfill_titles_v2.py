#!/usr/bin/env python3
# ruff: noqa
"""Backfill article titles and URLs in content_store_db and nlp_db.

The bronze JSON envelope has structure:
  { "url": ..., "raw_b64": "<base64 of raw article JSON>", ... }

EODHD raw article: { "title": "...", "link": "...", ... }
Finnhub raw article: { "headline": "...", "url": "...", ... }

Run from within docker network or with exposed ports:
  python3 scripts/backfill_titles_v2.py

Requires: pip install psycopg2-binary
"""

import base64
import hashlib
import json
import subprocess
import sys

try:
    import psycopg2
except ImportError:
    print("Install: pip install psycopg2-binary")
    sys.exit(1)

BRONZE_BUCKET = "worldview-bronze"


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def mc_cat(key: str) -> dict | None:
    """Read a MinIO object using the mc CLI inside the container."""
    full_key = f"local/{BRONZE_BUCKET}/{key}"
    result = subprocess.run(
        ["docker", "exec", "worldview-minio-1", "mc", "cat", full_key],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except Exception:
        return None


def mc_ls(prefix: str) -> list[str]:
    """List MinIO objects under a prefix using mc CLI."""
    full_prefix = f"local/{BRONZE_BUCKET}/{prefix}"
    result = subprocess.run(
        ["docker", "exec", "worldview-minio-1", "mc", "ls", "--recursive", full_prefix],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    lines = []
    for line in result.stdout.strip().split("\n"):
        parts = line.split()
        if parts:
            obj_name = parts[-1]  # last field is the object name
            lines.append(obj_name)
    return lines


def decode_article(envelope: dict) -> dict | None:
    """Decode the base64-encoded raw article JSON from the bronze envelope."""
    raw_b64 = envelope.get("raw_b64")
    if not raw_b64:
        return None
    try:
        raw = base64.b64decode(raw_b64).decode("utf-8", errors="replace")
        return json.loads(raw)
    except Exception:
        return None


def main() -> None:
    content_conn = psycopg2.connect("postgresql://postgres:postgres@localhost:5432/content_store_db")
    nlp_conn = psycopg2.connect("postgresql://postgres:postgres@localhost:5432/nlp_db")
    content_cur = content_conn.cursor()
    nlp_cur = nlp_conn.cursor()

    # Step 1: Backfill URLs in document_source_metadata from content_store_db
    print("Step 1: Backfilling URLs from content_store_db.documents...")
    content_cur.execute(
        "SELECT doc_id::text, source_url FROM documents WHERE source_url IS NOT NULL AND source_url != ''"
    )
    url_rows = content_cur.fetchall()
    url_updated = 0
    for doc_id, source_url in url_rows:
        nlp_cur.execute(
            "UPDATE document_source_metadata SET url = %s WHERE doc_id::text = %s AND (url IS NULL OR url = '')",
            (source_url, doc_id),
        )
        url_updated += nlp_cur.rowcount
    nlp_conn.commit()
    print(f"  Updated {url_updated} URL records in document_source_metadata")

    # Step 2: Backfill EODHD titles
    print("\nStep 2: Backfilling EODHD titles from bronze bucket...")
    content_cur.execute(
        "SELECT doc_id::text, source_url FROM documents "
        "WHERE source_type = 'eodhd' AND source_url IS NOT NULL AND (title IS NULL OR title = '')"
    )
    eodhd_rows = content_cur.fetchall()
    print(f"  Found {len(eodhd_rows)} EODHD docs without titles")

    eodhd_updated = 0
    for i, (doc_id, source_url) in enumerate(eodhd_rows):
        if i % 50 == 0:
            print(f"  Processing EODHD {i}/{len(eodhd_rows)}...")
        h = url_hash(source_url)
        key = f"content-ingestion/eodhd/{h}/raw/v1.json"
        envelope = mc_cat(key)
        if not envelope:
            continue
        article = decode_article(envelope)
        if not article:
            continue
        title = article.get("title") or None
        if title:
            content_cur.execute(
                "UPDATE documents SET title = %s WHERE doc_id::text = %s AND (title IS NULL OR title = '')",
                (title, doc_id),
            )
            nlp_cur.execute(
                "UPDATE document_source_metadata SET title = %s WHERE doc_id::text = %s AND (title IS NULL OR title = '')",
                (title, doc_id),
            )
            eodhd_updated += 1

    content_conn.commit()
    nlp_conn.commit()
    print(f"  Updated {eodhd_updated} / {len(eodhd_rows)} EODHD records")

    # Step 3: Backfill Finnhub titles (bulk listing)
    print("\nStep 3: Backfilling Finnhub titles from bronze bucket (bulk listing)...")
    finnhub_by_url: dict[str, str] = {}

    # Use mc ls to get all Finnhub object paths
    result = subprocess.run(
        [
            "docker",
            "exec",
            "worldview-minio-1",
            "mc",
            "ls",
            "--recursive",
            f"local/{BRONZE_BUCKET}/content-ingestion/finnhub/",
        ],
        capture_output=True,
        text=True,
    )

    finnhub_objects = []
    for line in result.stdout.strip().split("\n"):
        parts = line.split()
        if parts:
            # mc ls recursive output: [date] [time] [size] [unit] [key]
            key = parts[-1]
            if key.endswith(".json"):
                finnhub_objects.append(key)

    print(f"  Found {len(finnhub_objects)} Finnhub bronze objects")

    for i, key in enumerate(finnhub_objects):
        if i % 100 == 0:
            print(f"  Processing Finnhub {i}/{len(finnhub_objects)}...")
        # key comes from mc ls output - may be relative
        full_key = key if key.startswith("content-ingestion/") else f"content-ingestion/{key}"
        envelope = mc_cat(full_key)
        if not envelope:
            continue
        article = decode_article(envelope)
        if not article:
            continue
        article_url = article.get("url", "")
        headline = article.get("headline") or article.get("title") or None
        if article_url and headline:
            finnhub_by_url[article_url] = headline

    print(f"  Loaded {len(finnhub_by_url)} Finnhub articles with headlines")

    content_cur.execute(
        "SELECT doc_id::text, source_url FROM documents "
        "WHERE source_type = 'finnhub' AND source_url IS NOT NULL AND (title IS NULL OR title = '')"
    )
    finnhub_rows = content_cur.fetchall()

    fh_updated = 0
    for doc_id, source_url in finnhub_rows:
        headline = finnhub_by_url.get(source_url)
        if headline:
            content_cur.execute(
                "UPDATE documents SET title = %s WHERE doc_id::text = %s AND (title IS NULL OR title = '')",
                (headline, doc_id),
            )
            nlp_cur.execute(
                "UPDATE document_source_metadata SET title = %s WHERE doc_id::text = %s AND (title IS NULL OR title = '')",
                (headline, doc_id),
            )
            fh_updated += 1

    content_conn.commit()
    nlp_conn.commit()
    print(f"  Finnhub: Updated {fh_updated} / {len(finnhub_rows)} records")

    # Final summary
    nlp_cur.execute("SELECT COUNT(*) FROM document_source_metadata WHERE title IS NOT NULL AND title != ''")
    title_count = nlp_cur.fetchone()[0]
    nlp_cur.execute("SELECT COUNT(*) FROM document_source_metadata WHERE url IS NOT NULL AND url != ''")
    url_count = nlp_cur.fetchone()[0]
    nlp_cur.execute("SELECT COUNT(*) FROM document_source_metadata")
    total = nlp_cur.fetchone()[0]
    content_cur.execute("SELECT COUNT(*) FROM documents WHERE title IS NOT NULL AND title != ''")
    cs_title_count = content_cur.fetchone()[0]

    print("\nFinal state:")
    print(f"  content_store_db.documents with title: {cs_title_count}")
    print(f"  nlp_db.document_source_metadata with title: {title_count} / {total}")
    print(f"  nlp_db.document_source_metadata with url:   {url_count} / {total}")

    content_cur.close()
    nlp_cur.close()
    content_conn.close()
    nlp_conn.close()


if __name__ == "__main__":
    main()
