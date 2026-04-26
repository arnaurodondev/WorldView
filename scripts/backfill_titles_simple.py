#!/usr/bin/env python3
# ruff: noqa
"""Backfill article titles and URLs in document_source_metadata.

Reads directly from:
- content_store_db.documents for source_url
- worldview-bronze MinIO bucket for raw article JSON (title/headline)

Updates:
- content_store_db.documents.title
- nlp_db.document_source_metadata.title
- nlp_db.document_source_metadata.url

Run: python3 scripts/backfill_titles_simple.py
Requires: pip install psycopg2-binary minio
"""

import hashlib
import json
import sys

try:
    import psycopg2
    from minio import Minio
except ImportError:
    print("Install: pip install psycopg2-binary minio")
    sys.exit(1)


BRONZE_BUCKET = "worldview-bronze"
MINIO_ENDPOINT = "localhost:9000"


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def main() -> None:
    minio = Minio(MINIO_ENDPOINT, access_key="minioadmin", secret_key="minioadmin", secure=False)

    content_conn = psycopg2.connect("postgresql://postgres:postgres@localhost:5432/content_store_db")
    nlp_conn = psycopg2.connect("postgresql://postgres:postgres@localhost:5432/nlp_db")
    content_cur = content_conn.cursor()
    nlp_cur = nlp_conn.cursor()

    # Step 1: Backfill URLs in document_source_metadata from content_store_db
    print("Step 1: Backfilling URLs from content_store_db.documents...")
    content_cur.execute("SELECT doc_id, source_url FROM documents WHERE source_url IS NOT NULL AND source_url != ''")
    url_rows = content_cur.fetchall()
    url_updated = 0
    for doc_id, source_url in url_rows:
        nlp_cur.execute(
            "UPDATE document_source_metadata SET url = %s WHERE doc_id = %s AND (url IS NULL OR url = '')",
            (source_url, str(doc_id)),
        )
        url_updated += nlp_cur.rowcount
    nlp_conn.commit()
    print(f"  Updated {url_updated} URL records in document_source_metadata")

    # Step 2: Backfill EODHD titles
    print("\nStep 2: Backfilling EODHD titles from bronze bucket...")
    content_cur.execute(
        "SELECT doc_id, source_url FROM documents WHERE source_type = 'eodhd' AND source_url IS NOT NULL AND (title IS NULL OR title = '')"
    )
    eodhd_rows = content_cur.fetchall()
    print(f"  Found {len(eodhd_rows)} EODHD docs without titles")

    eodhd_updated = 0
    for doc_id, source_url in eodhd_rows:
        h = url_hash(source_url)
        key = f"content-ingestion/eodhd/{h}/raw/v1.json"
        try:
            obj = minio.get_object(BRONZE_BUCKET, key)
            data = json.loads(obj.read())
            title = data.get("title") or None
            if title:
                content_cur.execute(
                    "UPDATE documents SET title = %s WHERE doc_id = %s AND (title IS NULL OR title = '')",
                    (title, str(doc_id)),
                )
                nlp_cur.execute(
                    "UPDATE document_source_metadata SET title = %s WHERE doc_id = %s AND (title IS NULL OR title = '')",
                    (title, str(doc_id)),
                )
                eodhd_updated += 1
        except Exception as e:
            print(f"  EODHD miss for {source_url[:60]}: {e}")

    content_conn.commit()
    nlp_conn.commit()
    print(f"  Updated {eodhd_updated} / {len(eodhd_rows)} EODHD records")

    # Step 3: Backfill Finnhub titles (bulk listing)
    print("\nStep 3: Backfilling Finnhub titles from bronze bucket (bulk listing)...")
    finnhub_by_url: dict[str, str] = {}
    try:
        objects = list(minio.list_objects(BRONZE_BUCKET, prefix="content-ingestion/finnhub/", recursive=True))
        print(f"  Found {len(objects)} Finnhub bronze objects, reading...")
        for i, obj in enumerate(objects):
            if i % 100 == 0:
                print(f"    Processing {i}/{len(objects)}...")
            try:
                data_obj = minio.get_object(BRONZE_BUCKET, obj.object_name)
                data = json.loads(data_obj.read())
                article_url = data.get("url", "")
                headline = data.get("headline") or data.get("title") or None
                if article_url and headline:
                    finnhub_by_url[article_url] = headline
            except Exception:
                pass
    except Exception as e:
        print(f"  Finnhub listing error: {e}")

    print(f"  Loaded {len(finnhub_by_url)} Finnhub articles with headlines")

    content_cur.execute(
        "SELECT doc_id, source_url FROM documents WHERE source_type = 'finnhub' AND source_url IS NOT NULL AND (title IS NULL OR title = '')"
    )
    finnhub_rows = content_cur.fetchall()

    fh_updated = 0
    for doc_id, source_url in finnhub_rows:
        headline = finnhub_by_url.get(source_url)
        if headline:
            content_cur.execute(
                "UPDATE documents SET title = %s WHERE doc_id = %s AND (title IS NULL OR title = '')",
                (headline, str(doc_id)),
            )
            nlp_cur.execute(
                "UPDATE document_source_metadata SET title = %s WHERE doc_id = %s AND (title IS NULL OR title = '')",
                (headline, str(doc_id)),
            )
            fh_updated += 1

    content_conn.commit()
    nlp_conn.commit()
    print(f"  Updated {fh_updated} / {len(finnhub_rows)} Finnhub records")

    # Summary
    nlp_cur.execute("SELECT COUNT(*) FROM document_source_metadata WHERE title IS NOT NULL AND title != ''")
    title_count = nlp_cur.fetchone()[0]
    nlp_cur.execute("SELECT COUNT(*) FROM document_source_metadata WHERE url IS NOT NULL AND url != ''")
    url_count = nlp_cur.fetchone()[0]
    nlp_cur.execute("SELECT COUNT(*) FROM document_source_metadata")
    total = nlp_cur.fetchone()[0]

    print(f"\nFinal state in document_source_metadata ({total} total records):")
    print(f"  With title: {title_count}")
    print(f"  With URL:   {url_count}")

    content_cur.close()
    nlp_cur.close()
    content_conn.close()
    nlp_conn.close()


if __name__ == "__main__":
    main()
