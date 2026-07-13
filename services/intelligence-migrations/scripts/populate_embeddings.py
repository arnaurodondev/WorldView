"""Populate relation_type_registry embeddings at boot time.

For each row where embedding IS NULL, embeds
``f"{canonical_type}: {description}"`` via the configured embedding model
and writes the VECTOR(1024) result back.

Supports two embedding providers, selected by presence of EMBEDDING_API_KEY:

  * DeepInfra (default in prod) — when EMBEDDING_API_KEY is set, POSTs to the
    OpenAI-compatible ``{EMBEDDING_BASE_URL}/v1/embeddings`` endpoint with a
    Bearer token, model ``BAAI/bge-large-en-v1.5`` (1024-dim), and parses
    ``data[0].embedding``. This is the shared DeepInfra key the rest of the
    platform uses (see libs/ml-clients DeepInfraEmbeddingAdapter).
  * Ollama (local dev fallback) — when no API key is present, POSTs to the
    legacy ``{EMBEDDING_BASE_URL}/api/embeddings`` endpoint (no auth) with
    model ``bge-large:latest`` and parses the top-level ``embedding`` field.

Requires:
    INTELLIGENCE_DB_URL  — Postgres connection string
    EMBEDDING_BASE_URL   — API base
                           (DeepInfra: https://api.deepinfra.com/v1/openai;
                            Ollama:    http://ollama:11434)
    EMBEDDING_MODEL      — model name
                           (DeepInfra: BAAI/bge-large-en-v1.5;
                            Ollama:    bge-large:latest)
    EMBEDDING_API_KEY    — DeepInfra API key (optional; when unset, the Ollama
                           fallback is used for local dev)

Both providers emit identical 1024-dim vectors (BAAI/bge-large-en-v1.5 is the
same underlying model as the Ollama ``bge-large:latest`` tag), so the pgvector
schema is unchanged regardless of provider.

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
# When set, we speak DeepInfra's OpenAI-compatible /v1/embeddings API (Bearer
# auth); when empty/unset we fall back to the legacy Ollama /api/embeddings API
# (no auth) for local dev. This is the shared platform DeepInfra key.
EMBEDDING_API_KEY = os.environ.get("EMBEDDING_API_KEY", "").strip()
EXPECTED_DIM = 1024


def get_db_url() -> str:
    url = os.environ.get("INTELLIGENCE_DB_URL")
    if not url:
        raise RuntimeError("INTELLIGENCE_DB_URL environment variable is required")
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _extract_embedding(data: dict) -> list[float] | None:
    """Pull the embedding vector out of either provider's response shape.

    DeepInfra (OpenAI format): ``{"data": [{"embedding": [...], "index": 0}]}``
    Ollama (legacy format):    ``{"embedding": [...]}``
    """
    # OpenAI/DeepInfra shape (``data`` = non-empty list) takes precedence;
    # otherwise fall back to the Ollama shape (top-level ``embedding`` field).
    items = data.get("data")
    embedding = items[0].get("embedding") if isinstance(items, list) and items else data.get("embedding")

    if embedding and len(embedding) == EXPECTED_DIM:
        return embedding  # type: ignore[no-any-return]
    log.warning(
        "Unexpected embedding dimension",
        got=len(embedding) if embedding else 0,
        expected=EXPECTED_DIM,
    )
    return None


def embed_text(text_input: str) -> list[float] | None:
    """Embed one string. Returns None on failure (non-blocking by design).

    Selects the provider by EMBEDDING_API_KEY: DeepInfra's OpenAI-compatible
    ``/v1/embeddings`` when a key is present, else the legacy Ollama
    ``/api/embeddings`` endpoint.
    """
    headers = {"Content-Type": "application/json"}
    if EMBEDDING_API_KEY:
        # DeepInfra / OpenAI-compatible: batched ``input`` list + Bearer auth.
        url = f"{EMBEDDING_BASE_URL}/v1/embeddings"
        payload = json.dumps({"model": EMBEDDING_MODEL, "input": [text_input]}).encode()
        headers["Authorization"] = f"Bearer {EMBEDDING_API_KEY}"
    else:
        # Legacy Ollama: single ``prompt`` string, no auth.
        url = f"{EMBEDDING_BASE_URL}/api/embeddings"
        payload = json.dumps({"model": EMBEDDING_MODEL, "prompt": text_input}).encode()

    req = urllib.request.Request(  # noqa: S310 — URL built from trusted env var
        url,
        data=payload,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            data = json.loads(resp.read())
            return _extract_embedding(data)
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
            conn.execute(
                text("UPDATE relation_type_registry SET embedding = :embedding::vector WHERE type_id = :type_id"),
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
