#!/usr/bin/env python3
# ruff: noqa
"""One-off script to backfill article titles in content_store_db and nlp_db.

Reads raw article JSON from MinIO bronze bucket and extracts titles:
- EODHD articles: article["title"]
- Finnhub articles: article["headline"]

Matches documents by source_url (for EODHD) or by listing Finnhub bronze files.

Run inside the worldview network:
  docker run --rm --network worldview_default \
    -e MINIO_ENDPOINT=http://minio:9000 \
    -e MINIO_ACCESS_KEY=minioadmin \
    -e MINIO_SECRET_KEY=minioadmin \
    -e PG_DSN=postgresql://postgres:postgres@postgres:5432 \
    python:3.12-slim python backfill_article_titles.py
"""

import asyncio
import hashlib
import json
import os

import asyncpg
from minio import Minio

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://localhost:9000").replace("http://", "")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
BRONZE_BUCKET = "worldview-bronze"
PG_DSN_CONTENT = os.getenv("PG_DSN_CONTENT", "postgresql://postgres:postgres@localhost:5432/content_store_db")
PG_DSN_NLP = os.getenv("PG_DSN_NLP", "postgresql://postgres:postgres@localhost:5432/nlp_db")


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


async def backfill() -> None:
    client = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)

    content_conn = await asyncpg.connect(PG_DSN_CONTENT)
    nlp_conn = await asyncpg.connect(PG_DSN_NLP)

    try:
        # Get all documents without titles
        rows = await content_conn.fetch(
            "SELECT doc_id, source_type, source_url FROM documents WHERE title IS NULL OR title = ''",
        )
        print(f"Found {len(rows)} documents without titles")

        updated_content = 0
        updated_nlp = 0
        failed = 0

        for row in rows:
            doc_id = str(row["doc_id"])
            source_type = row["source_type"]
            source_url = row["source_url"] or ""

            title = None
            url = source_url or None

            try:
                if source_type == "eodhd" and source_url:
                    # EODHD: bronze key = eodhd/{sha256(source_url)}/raw/v1.json
                    h = url_hash(source_url)
                    key = f"eodhd/{h}/raw/v1.json"
                    try:
                        obj = client.get_object(BRONZE_BUCKET, f"content-ingestion/{key}")
                        data = json.loads(obj.read())
                        title = data.get("title") or None
                    except Exception as e:
                        print(f"  EODHD bronze read failed for {doc_id}: {e}")
                        failed += 1
                        continue

                elif source_type == "finnhub":
                    # Finnhub: bronze key = finnhub/{sha256(str(article_id))}/raw/v1.json
                    # We don't have the article_id directly, but we can search by source_url
                    # List all Finnhub bronze files and match by URL
                    # This is done in the bulk listing below
                    pass  # handled below

                if title and doc_id:
                    await content_conn.execute(
                        "UPDATE documents SET title = $1 WHERE doc_id = $2 AND (title IS NULL OR title = '')",
                        title,
                        doc_id,
                    )
                    updated_content += 1

                    await nlp_conn.execute(
                        "UPDATE document_source_metadata SET title = $1, url = $2 WHERE doc_id = $3 AND (title IS NULL OR title = '')",  # noqa: E501
                        title,
                        url,
                        doc_id,
                    )
                    updated_nlp += 1

            except Exception as e:
                print(f"  Error for {doc_id}: {e}")
                failed += 1

        print(
            f"\nEODHD pass: updated {updated_content} content_store records, {updated_nlp} nlp records, {failed} failed"
        )

        # Finnhub pass: bulk listing approach
        print("\nStarting Finnhub bulk listing...")
        finnhub_files = {}
        try:
            objects = client.list_objects(BRONZE_BUCKET, prefix="content-ingestion/finnhub/", recursive=True)
            for obj in objects:
                key = obj.object_name
                try:
                    data_obj = client.get_object(BRONZE_BUCKET, key)
                    data = json.loads(data_obj.read())
                    article_url = data.get("url", "")
                    headline = data.get("headline") or data.get("title") or None
                    if article_url:
                        finnhub_files[article_url] = headline
                except Exception:
                    continue
        except Exception as e:
            print(f"Finnhub listing failed: {e}")

        print(f"Loaded {len(finnhub_files)} Finnhub articles from bronze")

        # Match Finnhub documents by source_url
        finnhub_rows = await content_conn.fetch(
            "SELECT doc_id, source_url FROM documents WHERE source_type = 'finnhub' AND (title IS NULL OR title = '')",
        )

        fh_updated = 0
        for row in finnhub_rows:
            doc_id = str(row["doc_id"])
            source_url = row["source_url"] or ""
            headline = finnhub_files.get(source_url)
            if headline:
                await content_conn.execute(
                    "UPDATE documents SET title = $1 WHERE doc_id = $2 AND (title IS NULL OR title = '')",
                    headline,
                    doc_id,
                )
                await nlp_conn.execute(
                    "UPDATE document_source_metadata SET title = $1, url = $2 WHERE doc_id = $3 AND (title IS NULL OR title = '')",  # noqa: E501
                    headline,
                    source_url or None,
                    doc_id,
                )
                fh_updated += 1

        print(f"Finnhub pass: updated {fh_updated} / {len(finnhub_rows)} records")

        # Also update url for all existing document_source_metadata records
        # using content_store_db.documents.source_url
        url_updated = await nlp_conn.execute("""
            UPDATE document_source_metadata dsm
            SET url = d.source_url
            FROM dblink(
                'dbname=content_store_db host=localhost user=postgres password=postgres',
                'SELECT doc_id::text, source_url FROM documents WHERE source_url IS NOT NULL'
            ) AS d(doc_id text, source_url text)
            WHERE dsm.doc_id::text = d.doc_id
            AND (dsm.url IS NULL OR dsm.url = '')
        """)
        print(f"URL backfill: {url_updated}")

    finally:
        await content_conn.close()
        await nlp_conn.close()


if __name__ == "__main__":
    asyncio.run(backfill())
