# NLP chunk/title-denorm backfill plan (BUG #34 + BUG #35)

> **Status:** PLAN ONLY — do NOT run the mutating steps against live data without
> explicit user approval. The forward-fix code (this branch
> `feat/nlp-chunk-denorm-fixes`) stops *new* docs from being corrupted; this plan
> repairs the historical tail.

## Confirmed root causes (live `nlp_db` / `worldview-silver`, 2026-06-18)

### BUG #34 — chunk_index=0 is a raw JSON envelope, not prose
- `chunks` with `chunk_index=0`: **28,882** rows; **21,320 (73.8%)** start with `{`.
- **21,209 distinct docs** affected.
- The silver object DOES have a top-level `body` key, but `body` itself holds the
  **raw content-ingestion JSON re-encoded as a string** (doubly-encoded). Example
  (`worldview-silver/content-store/canonical/<doc>/body.json`):
  ```json
  {"doc_id": "...", "source_type": "eodhd", "title": "...",
   "body": "{\"date\": ..., \"content\": \"<the real prose>\", \"symbols\": [...]}"}
  ```
- Three inner shapes observed among broken chunk-0 rows (sampled 2000):
  | weight | inner keys | prose field |
  |--------|-----------|-------------|
  | 91.5%  | `content,date,link,sentiment,symbols,tags,title` (EODHD) | `content` |
  | 5.75%  | `date,source,summary,title,url` (Yahoo/seed) | `summary` |
  | 2.75%  | `author,content,description,publishedAt,source,title,url,urlToImage` (NewsAPI) | `content` |
- **Upstream origin (out of scope for this branch, file separately):**
  `content-store/.../use_cases/process_article.py` maps `eodhd`/`newsapi` →
  `content_type="html"` and runs `clean()` (readability + bleach). bleach over a
  JSON string finds no tags and returns the JSON intact → silver `body` = raw JSON.
  The nlp-side `download_article` fix (`_recover_prose`) compensates, but the
  durable fix is to extract the prose field in content-store's cleaner/`_guess_content_type`.

### BUG #35 — NULL `chunks.title_denorm` blinds the learned router
- NULL/empty `title_denorm` by source: **sec_edgar 1392**, **newsapi 186** (all
  other sources fully populated).
- `document_source_metadata.title` is ALSO NULL for these (content-store DB has 0
  titles for all 5056 sec_edgar + 437 newsapi docs) — so dsm is NOT a reliable
  recovery source, contrary to the original ticket. The reliable source is the
  **silver envelope**: NewsAPI's title lives in the inner raw-news JSON inside
  `body` (recoverable → 186 docs). sec_edgar exposes no title anywhere in silver.
- Routing impact (effective tier): sec_edgar is mostly **MEDIUM** (the static
  regulatory-filing override + C-8 titleless fallback already protect it), so the
  routing harm is concentrated on **newsapi** (≈112 docs in LIGHT).

## Forward fix (already on this branch)
- `download_article` → `_recover_prose` peels doubly-encoded `body` to inner prose.
- `extract_title_from_silver` + consumer wiring recovers title from silver when the
  event has none, feeding both `title_denorm` and `document_source_metadata.title`.

## Backfill steps (DO NOT RUN without approval)

The cleanest repair re-runs the NLP pipeline for affected docs against the
**already-fixed** consumer code, so chunks/title_denorm are regenerated correctly
rather than patched in place. Two options:

### Option A (preferred) — re-emit `content.article.stored.v1` for affected docs
1. Deploy this branch to the nlp-pipeline consumer first (so re-processing uses the fix).
2. Build the affected doc list:
   ```sql
   -- #34 candidates
   CREATE TEMP TABLE reprocess_docs AS
   SELECT DISTINCT doc_id FROM chunks WHERE chunk_index = 0 AND left(chunk_text, 1) = '{';
   -- add #35 newsapi titleless docs
   INSERT INTO reprocess_docs
   SELECT DISTINCT c.doc_id FROM chunks c
   JOIN document_source_metadata d ON d.doc_id = c.doc_id
   WHERE (c.title_denorm IS NULL OR c.title_denorm = '') AND d.source_type = 'newsapi'
   ON CONFLICT DO NOTHING;
   ```
   Estimate: ~21,209 (#34) ∪ 186 (#35 newsapi) ≈ **21,300 docs**.
3. For each, look up `content_store_db.documents.minio_silver_key` + `source_type`
   and re-publish a `content.article.stored.v1` event (use the existing replay/seed
   tooling, NOT a hand-rolled producer). The fixed consumer's idempotency check is
   keyed on `routing_decisions.get_by_doc(doc_id)` — so **delete the existing NLP
   artifacts for those docs first** (chunks, sections, entity_mentions,
   routing_decisions, embeddings) inside one transaction per doc, or the consumer
   will `skip_already_processed`.
4. Throttle: re-processing 21k docs runs NER + embeddings + (for promoted tiers)
   LLM extraction. Rate-limit to protect DeepInfra budget; run as a backfill batch
   (`is_backfill=true`) off-peak.

### Option B — in-place SQL repair of chunk-0 + title_denorm (cheaper, lossy)
Only fixes the *stored text*, NOT downstream NER/embeddings/extraction (which were
computed on the corrupted text), so quality stays degraded. Use only if a full
re-process is infeasible. Sketch (validate on a copy first):
```sql
-- #35 newsapi: backfill title_denorm from silver-derived dsm.title (after the
-- forward fix has repopulated dsm.title for newly processed docs).
UPDATE chunks c SET title_denorm = d.title
FROM document_source_metadata d
WHERE d.doc_id = c.doc_id AND d.source_type = 'newsapi'
  AND (c.title_denorm IS NULL OR c.title_denorm = '') AND d.title IS NOT NULL;
```
The chunk-0 text repair cannot be done reliably in pure SQL (needs JSON peeling +
re-sectioning + re-embedding) — Option A is required for #34.

## Recommendation
Run **Option A** for #34 (the corrupted text invalidates all downstream NLP for
21k docs). For #35 sec_edgar (1392 docs, no silver title), the static
regulatory-floor already routes them to MEDIUM, so no backfill is needed — accept
NULL title_denorm. For #35 newsapi (186 docs), Option A folds them into the same
re-process pass.
