"""Seed bge-large embeddings for relation_type_registry.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-03

Background
----------
``relation_type_registry`` stores 27 canonical relation types (e.g.
``acquired_by``, ``analyst_rating``) with a ``vector(1024)`` ``embedding``
column.  S7 enriched-consumer Block 11 uses a 3-step canonicalization:

  Step 1 — exact match on ``canonical_type``
  Step 2 — ANN cosine-distance soft-map  (``WHERE embedding IS NOT NULL``)
  Step 3 — emit ``relation.type.proposed.v1`` (canonical_type = NULL)

Without embeddings, Step 2 is permanently bypassed: every predicate that is
not an exact string match falls through to Step 3, so no relation edge is
written to the ``relations`` table.  This migration seeds the embeddings using
the same model (``bge-large:latest`` via Ollama) used by the enriched consumer
at runtime, so ANN distances are consistent.

Behaviour when Ollama is unavailable
-------------------------------------
If Ollama is not reachable (e.g. CI, offline build), the migration finishes
successfully and emits a warnings.warn().  Embeddings remain NULL; Step 2 stays
bypassed until the migration is re-applied on a system with Ollama running.
To re-apply: downgrade to 0012, then upgrade to head.

Idempotency
-----------
Only rows with ``embedding IS NULL`` are updated.  Re-running is safe.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import warnings
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str = "0012"
branch_labels = None
depends_on = None

# Same defaults as enriched_consumer_main.py.
_OLLAMA_URL = "http://ollama:11434/api/embeddings"
_MODEL_ID = "bge-large:latest"
# Truncate to 1500 chars to stay within BERT 512-token context (BP-121).
_MAX_CHARS = 1500
_TIMEOUT_S = 60


def _get_embedding(text: str) -> list[float] | None:
    """Return 1024-dim embedding from Ollama, or None if unavailable."""
    payload = json.dumps({"model": _MODEL_ID, "prompt": text[:_MAX_CHARS], "options": {"num_ctx": 512}}).encode()
    req = urllib.request.Request(  # noqa: S310
        _OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:  # noqa: S310
            body: dict[str, Any] = json.loads(resp.read())
            return body["embedding"]
    except (urllib.error.URLError, OSError, KeyError, json.JSONDecodeError):
        return None


def upgrade() -> None:
    conn = op.get_bind()

    rows = conn.execute(
        sa.text(
            "SELECT type_id, canonical_type FROM relation_type_registry "
            "WHERE embedding IS NULL AND is_active = true "
            "ORDER BY canonical_type"
        )
    ).fetchall()

    if not rows:
        return

    warned = False

    for type_id, canonical_type in rows:
        emb = _get_embedding(canonical_type)
        if emb is None:
            if not warned:
                warnings.warn(
                    f"0013: Ollama not reachable at {_OLLAMA_URL}. "
                    "relation_type_registry embeddings remain NULL; "
                    "S7 Block 11 Step 2 (ANN soft-map) will be bypassed until "
                    "this migration is re-applied with Ollama running.",
                    stacklevel=2,
                )
                warned = True
            continue

        # pgvector accepts a text array literal cast to vector.
        vec_literal = "[" + ",".join(str(v) for v in emb) + "]"
        conn.execute(
            sa.text("UPDATE relation_type_registry " "SET embedding = :vec::vector " "WHERE type_id = :tid"),
            {"vec": vec_literal, "tid": str(type_id)},
        )


def downgrade() -> None:
    op.execute(sa.text("UPDATE relation_type_registry SET embedding = NULL"))
