# SEC EDGAR / NewsAPI Title Investigation — Root Cause of NULL `chunks.title_denorm`

**Date:** 2026-06-15
**Type:** Read-only investigation (no code or data changes)
**Trigger:** [`2026-06-15-routing-shadow-assessment.md`](2026-06-15-routing-shadow-assessment.md) §4 — 111 title-less docs (86 `sec_edgar` + 25 `newsapi`) score ~0.18 p_yield and the learned router dumps them to `light`; `sec_edgar` was 100% extraction under the static router (highest-value source). That assessment added a static-tier fallback as mitigation. This task finds the **root cause** of the missing title.

---

## TL;DR

The missing title is **not a denormalization bug** — there is no title sitting in `document_source_metadata` (or anywhere downstream) that we fail to copy onto chunks. The title is **NULL from the very first ingestion hop**, because the SEC EDGAR and NewsAPI content-ingestion adapters never populate `FetchResult.title`. Per-source classification:

- **`newsapi` → (A) Processing bug.** NewsAPI.org always returns a `title` and it is even serialized into the raw bronze bytes, but the adapter drops it (never sets `FetchResult.title`). **Fix: plumb the existing `article["title"]` through.**
- **`sec_edgar` → (B) Source-data gap.** The EFTS search index has no headline field; it provides form type + company name + dates. **Fix: synthesize a title at ingestion** (e.g. `"{company} {form_type} filing ({date})"`).

Both share the same code-shaped defect (adapter omits `title=`), but the remedy differs because only NewsAPI actually carries a headline.

---

## 1. The title pipeline (end-to-end trace)

`chunks.title_denorm` is stamped in **nlp-pipeline** from a single source — `doc_title`, which is read straight off the Kafka event:

```
article_consumer.py:727   doc_title = str(value["title"]) if value.get("title") is not None else None
article_consumer.py:1095  chunks = [dataclasses.replace(c, title_denorm=doc_title, ...) for c in chunks]
```

`value["title"]` originates in **content-ingestion**, where each adapter builds a `FetchResult` and `fetch_and_write.py` forwards `result.title` into the raw-article event:

```
fetch_and_write.py:197    title=result.title,
fetch_and_write.py:59     "title": title,            # → content.article.raw.v1 payload
content-store article_consumer.py:143   title=value.get("title")   # persisted into documents / silver
```

So the title flows: **adapter `FetchResult.title` → `content.article.raw.v1` event → content-store `documents` / silver → nlp event `value["title"]` → `doc_title` → `chunks.title_denorm`** (and `document_source_metadata.title`).

`FetchResult` (content-ingestion `domain/entities.py:59`) **has** a `title: str | None = None` field. The working adapters set it explicitly:

| adapter | sets title from | line |
|---|---|---|
| eodhd | `article.get("title")` | adapter.py:112,125 |
| eodhd_ticker_news | `article.get("title")` | adapter.py:219,232 |
| finnhub | `article.get("headline")` | adapter.py:125,138 |
| **sec_edgar** | **never sets `title=`** (defaults to None) | adapter.py:172-184 |
| **newsapi** | **never sets `title=`** (defaults to None) | adapter.py:105-117 |

That is the entire bug: the two failing adapters omit the `title=` argument when constructing `FetchResult`, so it stays at its `None` default and the NULL propagates the whole way down.

---

## 2. Database evidence (quantification)

`document_source_metadata.title` in `nlp_db` — titled vs title-less, **by source**:

| source_type | docs | has DSM title |
|---|---:|---:|
| eodhd_ticker_news | 11,314 | 11,314 (100%) |
| finnhub | 9,389 | 9,389 (100%) |
| eodhd | 5,141 | 5,141 (100%) |
| **sec_edgar** | **2,846** | **0 (0%)** |
| **newsapi** | **174** | **0 (0%)** |

And `chunks.title_denorm` (only chunked docs):

| source_type | docs w/ chunks | chunks w/ title | total chunks |
|---|---:|---:|---:|
| eodhd | 5,129 | 10,171 | 10,171 (100%) |
| finnhub | 4,978 | 5,347 | 5,347 (100%) |
| **newsapi** | **174** | **0** | **175 (0%)** |
| **sec_edgar** | **1,266** | **0** | **1,266 (0%)** |

**Decisive:** every `sec_edgar` (2,846) and `newsapi` (174) doc has NULL title at **both** the DSM layer and the chunk layer — not a subset, **all of them**. Critically, `document_source_metadata.title` is **also** empty (0/2,846, 0/174), so this is **not** a denormalization bug where DSM holds a title that chunks fail to copy. The title is genuinely absent the whole way back to ingestion. Every other source is 100% titled, which isolates the defect to these two adapters.

(The shadow window saw only 86/25 of these because it is a 64h slice; the corpus-wide impact is 2,846 sec_edgar + 174 newsapi docs.)

---

## 3. Per-source root cause

### `newsapi` — (A) Processing bug, title EXISTS

NewsAPI.org's `/everything` response always includes a per-article `title` (their documented schema). The adapter already has it in hand:

```python
# newsapi/adapter.py:91-117
for article in articles:
    article_url = article.get("url", "")          # reads url...
    ...
    raw_bytes = json.dumps(article).encode("utf-8")  # title IS inside raw_bytes here
    results.append(FetchResult(
        source_id=source.id,
        url=article_url,
        ...
        # ← no title= ; FetchResult.title stays None
    ))
```

The headline is sitting in `article["title"]` (and is even round-tripped into the bronze JSON), but it is never lifted onto `FetchResult.title`. **Pure processing/mapping bug.**

**Fix:** add `title=article.get("title") or None` to the `FetchResult(...)`. One line, mirrors eodhd/finnhub. Recovers all 174 docs going forward; the existing 174 can be backfilled from the bronze JSON if desired.

### `sec_edgar` — (B) Source-data gap, title must be SYNTHESIZED

The EFTS search index (`_source` block) has **no headline field**. The adapter already destructures it for other fields (`adsh`, `ciks`, `period_ending`, `file_date`) and could equally read the form type and company name (EFTS exposes `form`/`file_type` and `display_names`, e.g. `"Apple Inc. (AAPL) (CIK 0000320193)"`). There is no natural headline to plumb — it must be constructed.

**Fix:** synthesize a deterministic title at ingestion, e.g.

```
"{company_name} {form_type} filing ({YYYY-MM-DD})"
→ "Apple Inc. 10-K filing (2026-01-31)"
```

using `display_names[0]` (strip the trailing CIK/ticker parens), `form`/`file_type`, and the already-parsed `published_at`. This gives the learned router and lexical/retrieval layers a usable, information-bearing title (form type is exactly the signal the static router's `document_type=0.88` prior captured). 2,846 existing docs can be backfilled from the same EFTS fields or re-derived from `documents` metadata.

---

## 4. Relationship to the shadow-assessment mitigation

The static-tier fallback already added (`learned_router_titleless_fallback`, article_consumer.py:939-943) is the correct **defensive** stopgap — it stops the blind learned gate from dumping title-less SEC filings to `light`. But it leaves the documents permanently title-less, which also degrades **lexical/FTS retrieval** (weight-A `title_denorm` in `tsv_english`, migration 0017) and any title-dependent UI/chat surface. The fixes here are the **upstream root-cause** remedy; the fallback should remain as belt-and-suspenders until the backfill lands and titled SEC/newsapi docs flow through the normal learned path.

---

## 5. Recommendation

| source | class | fix | effort |
|---|---|---|---|
| `newsapi` | (A) processing bug | set `title=article.get("title")` in `newsapi/adapter.py` `FetchResult` | 1 line + test |
| `sec_edgar` | (B) source gap | synthesize `"{company} {form} filing ({date})"` from EFTS `display_names`/`form`/`published_at` in `sec_edgar/adapter.py` | small + test |

Both are forward-fixes at the ingestion boundary, so every layer downstream (DSM, silver, chunks `title_denorm`, FTS weight-A, learned-router input) is populated automatically with no per-layer plumbing. Backfill the 2,846 + 174 existing docs from EFTS/bronze to recover historical coverage. Keep the static-tier title-less fallback in place during the transition.

**Answer to the framing question:** BOTH — `newsapi` is a processing bug (title exists, dropped); `sec_edgar` is a genuine source-data gap (no headline at source, must be synthesized). Neither is a denormalization bug: `document_source_metadata.title` is itself NULL for 100% of affected docs.
