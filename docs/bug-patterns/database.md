# Bug Patterns — Database (migrations, Alembic lineage, DDL ownership)

Detailed write-ups for database/migration bug patterns indexed in
[`../BUG_PATTERNS.md`](../BUG_PATTERNS.md).

---

## BP-716 — `intelligence-migrations` does NOT own `nlp_db` DDL (three separate Alembic lineages)

**Symptom / trap**: A recurring wrong assumption that every "intelligence"-adjacent table migrates through the `intelligence-migrations` init container. Authoring an `nlp_db` column change there would run it against the wrong physical database (or not at all).

**Reality (verified in each `alembic/env.py`)** — there are THREE independent service Alembic lineages:
- `rag_db` DDL → **rag-chat** (`services/rag-chat/alembic`).
- `nlp_db` DDL → **nlp-pipeline itself** (`services/nlp-pipeline/alembic/env.py`: "This service (S6 NLP Pipeline) ONLY manages nlp_db"). Its `ALEMBIC_ENABLED=false` flag gates ONLY its *intelligence_db* adapter connection — NOT its own nlp_db migrations, which always run.
- `intelligence_db` DDL → **intelligence-migrations** (`INTELLIGENCE_DB_URL`; `target_metadata=None`, SQL-only). S7 knowledge-graph owns no Alembic dir and runs `ALEMBIC_ENABLED=false`.

**Prevention**: Before writing any migration, open the target service's `alembic/env.py` and confirm which physical DB its `ALEMBIC_URL` / `*_DATABASE_URL` binds to. A column added to the wrong lineage is a silent no-op (or a wrong-DB error). This was resolved as OQ-2 in PLAN-0117, whose W2 correctly split the `llm_usage_log` column additions across rag-chat `0010` (rag_db), nlp-pipeline `0023` (nlp_db), and intelligence-migrations `0064` (intelligence_db).

Status: documented guard. References: `services/nlp-pipeline/alembic/env.py`, `services/intelligence-migrations/alembic/env.py`, PLAN-0117 §6.4.
