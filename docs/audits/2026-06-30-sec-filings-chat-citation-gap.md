# SEC Filings Chat Citation Gap — Investigation + Resolution (2026-06-30)

Branch: `feat/chat-sec-filings-tool`

## Question

The chat had no filings tool, and fundamentals (`handlers/market.py`) come from EODHD
aggregates with `url=None` — no per-datapoint or per-filing source link. Are raw SEC
filings ingested anywhere, and can the chat cite them with a clickable URL?

## Finding: filings ARE ingested

SEC EDGAR filings flow through the standard content pipeline:

- **Ingestion (S4 content-ingestion)**: `infrastructure/adapters/sec_edgar/{adapter,client}.py`
  fetch filings via the EFTS full-text search API. The `sec_edgar` source is **seeded and
  enabled by default** (migration `0008_seed_default_sources`, `source_type="sec_edgar"`).
  Each `FetchResult` carries:
  - `url` = canonical EDGAR filing-index URL,
    `https://www.sec.gov/Archives/edgar/data/{cik}/{acc_no}/{acc}-index.htm` (BP-460)
  - `published_at` = filing/period date
  - raw bytes of the filing index page → MinIO bronze → `content.article.raw.v1`
- **Storage (S5 content-store → S6 NLP)**: filings become documents with
  `document_source_metadata.source_type = 'sec_edgar'`, `source_url` = the EDGAR URL,
  `published_at` = filed date. They are chunked + embedded like any document. The corpus
  comment in `article_consumer.py` confirms live data ("86 sec_edgar" docs).

So filing metadata WITH a clickable URL is available via an existing REST read path.

## Gap: there was no read/tool that exposed them, and a latent filter bug

1. **No filings tool** in the 26-tool chat catalog.
2. **`form_type` is not persisted as a structured field.** Every filing is stored under the
   single generic `source_type='sec_edgar'`; the per-form type (10-K/10-Q/8-K) is lost after
   ingestion. Any form-type filter can only be best-effort (recovered from text).
3. **Latent bug (pre-existing, NOT fixed here):** the S6 FTS endpoint
   `GET /api/v1/search/documents?source_type=sec_edgar` maps via
   `_SOURCE_TYPE_MAP["sec_edgar"] = ['sec_10k','sec_8k','sec_10q']` — none of which match the
   stored `'sec_edgar'` literal — so that endpoint returns **zero** filings for the `sec_edgar`
   filter. (`search_documents` chat tool advertises `source_types=['sec_filing']` to the LLM,
   which also fails to match.) Recorded for a separate fix; see Follow-ups.

## Resolution: `get_filings` chat tool (implemented)

Added the 27th catalog tool `get_filings`. It uses the **chunk-search** read path, which
filters `dsm.source_type = ANY(:source_types)` verbatim (correct) rather than the broken FTS
map:

- Read path: `S6Port.search_chunks(source_types=['sec_edgar'], entity_ids=[...])`
  (rag-chat → S6 direct REST — the existing tool pattern; R9 safe-degrade to `[]`).
- Resolves `ticker → entity_id` (S6 alias lookup), accepts `entity_id`, or falls back to the
  scoped `EntityContext`.
- Dedupes chunk hits to **one row per filing** (by `doc_id`), sorts newest-first, recovers the
  form label (10-K/8-K/…) best-effort from the chunk text/title.
- Each result is a `RetrievedItem` with `citation_meta.url` = the EDGAR filing-index URL,
  `title` = "{FORM} filing — {date}", `source_name="sec_edgar"`, `published_at` = filed date,
  `trust_weight=0.95` (primary-source authority).
- `form_type` filter prefers exact-form filings but degrades to all recent filings (logged)
  rather than returning empty.

### Files changed

- `services/rag-chat/src/rag_chat/application/pipeline/handlers/news.py` — `_handle_get_filings`
  + dispatch + form-label regex.
- `services/rag-chat/src/rag_chat/application/pipeline/tool_registry_builder.py` — `ToolSpec`.
- `libs/tools/src/tools/capability_manifest.yaml` — manifest entry (parity-guarded).
- Tests: `tests/unit/application/pipeline/handlers/test_get_filings_handler.py` (9 cases);
  registry/definition count assertions bumped 26 → 27.
- Docs: `docs/services/rag-chat.md`, `services/rag-chat/.claude-context.md`.

## Follow-ups (out of scope here)

- **Fix the FTS `_SOURCE_TYPE_MAP["sec_edgar"]`** to include `'sec_edgar'` (or align the
  ingested source_type to per-form types) so `search_documents`'s filing filter works too.
- **Persist `form_type` + `accession_number` structurally** (e.g. on
  `document_source_metadata`) so filings can be filtered/listed by form without text scraping.
- Optionally proxy a dedicated filings read endpoint through S9 for the web frontend (R14).
