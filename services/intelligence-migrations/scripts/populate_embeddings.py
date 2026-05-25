"""Populate relation_type_registry embeddings at boot time.

For each row where embedding IS NULL, embeds
``f"{canonical_type}: {description}"`` via the configured embedding model
and writes the VECTOR(1024) result back.

Requires:
    INTELLIGENCE_DB_URL  — Postgres connection string
    EMBEDDING_BASE_URL   — Ollama API base (default http://ollama:11434)
    EMBEDDING_MODEL      — model name (default bge-large:latest — Ollama model tag)

Tolerates embedding service unavailability: logs a warning and exits 0
so the init container does not block S6/S7 startup. Embeddings will be
populated on next restart or via a manual re-run.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

import sqlalchemy as sa
import structlog
from sqlalchemy import text

structlog.configure(
    processors=[
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
)
log = structlog.get_logger("populate_embeddings")

EMBEDDING_BASE_URL = os.environ.get("EMBEDDING_BASE_URL", "http://ollama:11434")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "bge-large:latest")
EXPECTED_DIM = 1024


def get_db_url() -> str:
    url = os.environ.get("INTELLIGENCE_DB_URL")
    if not url:
        raise RuntimeError("INTELLIGENCE_DB_URL environment variable is required")
    return url.replace("postgresql+asyncpg://", "postgresql://")


def embed_text(text_input: str) -> list[float] | None:
    """Call Ollama /api/embeddings endpoint. Returns None on failure."""
    payload = json.dumps({"model": EMBEDDING_MODEL, "prompt": text_input}).encode()
    url = f"{EMBEDDING_BASE_URL}/api/embeddings"
    req = urllib.request.Request(  # noqa: S310 — URL built from trusted env var
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            data = json.loads(resp.read())
            embedding = data.get("embedding")
            if embedding and len(embedding) == EXPECTED_DIM:
                return embedding  # type: ignore[no-any-return]
            log.warning(
                "Unexpected embedding dimension",
                got=len(embedding) if embedding else 0,
                expected=EXPECTED_DIM,
            )
            return None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("Embedding service unavailable", error=str(exc))
        return None


def main() -> None:
    engine = sa.create_engine(get_db_url(), pool_pre_ping=True)

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT type_id, canonical_type, description FROM relation_type_registry WHERE embedding IS NULL")
        ).fetchall()

        if not rows:
            log.info("All relation types already have embeddings — nothing to do.")
            return

        log.info("Found relation types needing embeddings", count=len(rows))
        updated = 0

        for type_id, canonical_type, description in rows:
            input_text = f"{canonical_type}: {description}" if description else canonical_type
            embedding = embed_text(input_text)

            if embedding is None:
                log.warning(
                    "Skipping — embedding service returned no result, will retry on next run",
                    canonical_type=canonical_type,
                )
                continue

            # Explicit ::vector cast required — psycopg2 binds the param as
            # text and pgvector won't implicitly coerce without the cast.
            # BP-180: `:param::type` syntax is invalid with psycopg2 parameter
            # substitution — must use CAST(:param AS type) instead.
            conn.execute(
                text(
                    "UPDATE relation_type_registry"
                    " SET embedding = CAST(:embedding AS vector)"
                    " WHERE type_id = :type_id"
                ),
                {"embedding": str(embedding), "type_id": type_id},
            )
            updated += 1
            log.info("Embedded", canonical_type=canonical_type)

        conn.commit()
        log.info("Done", updated=updated, total=len(rows))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("Fatal error in populate_embeddings")
        # Exit 0 so init container does not block S6/S7 startup.
        # Embeddings can be populated on next restart.
        sys.exit(0)
