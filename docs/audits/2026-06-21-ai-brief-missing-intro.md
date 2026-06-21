# AI Brief Missing Intro Paragraph — Investigation

**Date:** 2026-06-21
**Branch:** `feat/md-reliability-followups`
**Type:** Read-only investigation (no code changes)
**Symptom:** The daily morning brief on the dashboard renders only its structured
sections ("Market Snapshot", "Your Portfolio Today", …) and is MISSING the
opening general/overview paragraph (the lead/summary narrative) that used to
appear above the sections.

---

## TL;DR — Root Cause

**This is a DATA (backend) bug, not a rendering bug.** The morning brief served to
the dashboard has `summary_paragraph = null`, `summary = null`, `lead = null`, and
its entire body sits in `narrative` starting with `## Details`. The frontend's
collapsed-view lead source is

```ts
collapsedSource = summary_paragraph || summary || narrative   // MorningBriefCard.tsx:522-523
```

so with all three lead-bearing fields null it falls back to rendering the raw
`narrative` (the sections) and there is no intro paragraph to show. The frontend
is behaving correctly.

**Why the backend lost the intro:** the morning brief is served from the
**pre-generation cache** (`RAG_CHAT_BRIEF_PREGEN_ENABLED=true`), and the
pre-generation worker's payload serializer **drops the `summary_paragraph` field**.
The use case (`execute_public_morning`) correctly synthesises `summary_paragraph`
(via `inject_missing_summary`), but `MorningBriefPregenerationWorker._build_payload`
never copies it into the cached `PublicBriefingResponse`. The cached payload the
dashboard reads therefore always has `summary_paragraph = null`.

This is a **regression of the BP-624 fix** (PLAN-0103 W3, commit `d4adf3962`),
which added `summary_paragraph` to the schema and to **two** of the three payload
builders but **missed the pre-generation worker** — the path that actually feeds
the dashboard.

---

## The precise fix (one line)

**File:** `services/rag-chat/src/rag_chat/application/workers/morning_brief_pregeneration_worker.py`
**Method:** `_build_payload` (≈ lines 299–311)

Add the missing field to the `PublicBriefingResponse(...)` construction:

```python
response = PublicBriefingResponse(
    narrative=result.get("content", result.get("narrative", "")),
    risk_summary=result.get("risk_summary") or {},
    citations=result.get("citations", []),
    generated_at=result["generated_at"],
    cached=False,
    entity_id=None,
    summary=result.get("summary"),
    sections=result.get("sections", []),
    confidence=result.get("confidence", 1.0),
    lead=result.get("lead"),
    is_stale=False,
    summary_paragraph=result.get("summary_paragraph"),   # ← ADD THIS LINE (BP-624 parity)
)
```

After deploy, the cache will need to be repopulated — either wait for the next
pre-gen pass (`RAG_CHAT_BRIEF_PREGEN_INTERVAL_HOURS=1`) or evict the stale keys:

```
DEL briefing:morning:v2:<user_id>  briefing:morning:lastgood:<user_id>
```

(The next on-demand GET will then regenerate via the main route, which already
includes `summary_paragraph` — so even before the next pre-gen pass an
on-demand miss will be correct.)

A regression test should assert that `_build_payload` round-trips
`summary_paragraph` (mirror the existing `lead`/`summary`/`sections` assertions in
`tests/unit/.../test_*pregeneration*`).

---

## Evidence

### 1. Live payload (served, cached, fresh)

`POST /v1/auth/dev-login` then `GET /v1/briefings/morning`:

```
cached: True | is_stale: False
summary: None | summary_paragraph: None | lead: None
narrative startswith: '## Details  \n**Market Snapshot'
KEYS: id, narrative, risk_summary, citations, generated_at, cached, entity_id,
      summary, sections, confidence, lead, is_stale, summary_paragraph
n_sections: 0
```

`cached:True, is_stale:False` = served from the **fresh** pre-gen key
(`briefing:morning:v2:{user_id}`) written by the worker. All three lead fields are
null; `sections` is empty; the whole body is in `narrative`.

### 2. Persisted brief (rag_db.user_briefs)

```
SELECT lead IS NULL, length(lead), json_array_length(sections_json)
FROM user_briefs WHERE brief_type='morning' ORDER BY generated_at DESC LIMIT 5;
-- lead_null=t, lead_len=(empty), n_sections=0   for every recent morning brief
```

(Note: the DB `headline` column holds the brief body — sections — and `lead` is
empty. The DB table has columns `headline, lead, sections_json, citations_json,
confidence, source_version`; it does NOT have `summary`/`narrative`/
`summary_paragraph` — those are response-layer fields. The dashboard reads the
**Valkey cache**, not this table, but both reflect the same empty-lead reality.)

### 3. Frontend rendering is correct

`apps/worldview-web/components/dashboard/MorningBriefCard.tsx`:

- L388–396: `safeNarrative / safeSummary / safeSummaryParagraph` derived from the
  payload (after citation-marker/stale-metadata stripping).
- L522–523: `collapsedSource = summaryParagraphWithLinks || summaryWithLinks ||
  narrativeWithLinks`.
- L554–561: `useStructuredCollapsed` only when `sections` carry bullets; here
  `sections=[]`, so this is false → the **prose fallback** path (L734–766) renders
  `collapsedSource`.
- With `summary_paragraph` and `summary` both null, `collapsedSource` === the raw
  `narrative` (the `## Details` sections). The card's `h2/h3` overrides collapse
  the `## Details` heading to inline, so the user sees the section bullets with no
  intro paragraph — exactly the reported symptom.

`BriefCatalystPreview.tsx` is NOT involved here — it only renders when
`sections` is non-empty (the structured-collapsed path), which is not the case for
the live v4.x brief. It does not drop the lead.

### 4. The backend DOES try to produce the intro

`services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py`:

- L478: `split_summary_paragraph(content)` extracts the LLM's `## Summary` block.
- L572: `inject_missing_summary(...)` synthesises a `summary_paragraph` from a
  real cited bullet when the LLM omitted `## Summary` (no fabrication).
- L717: returns `"summary_paragraph": summary_paragraph` in the result dict.

The prompt (`libs/prompts/src/prompts/briefing/morning.py`, v4.8) still mandates
the leading `## Summary` block (L238–243, L294–299). So the prompt is correct and
the use case output is correct — the field is produced; it is just **dropped at
the cache-serialization boundary**.

---

## Why two of three builders are right and one is wrong

`summary_paragraph` is threaded through every payload builder EXCEPT the
pre-gen worker:

| Builder | Location | Has `summary_paragraph`? |
|---|---|---|
| Main on-demand response | `public_briefings.py:379` | YES |
| Background regen (stale fallback) | `public_briefings.py:266` | YES |
| **Pre-generation worker** | `morning_brief_pregeneration_worker.py:299–311` | **NO ← bug** |

Because pre-gen is enabled, the worker's payload is the one the dashboard almost
always reads (cached + fresh), so the missing field is always visible to the user.

---

## Git archaeology — confirms regression, identifies SHA

- `474dbd3d8` — *PLAN-0094 W2+W3: daily brief pre-generation + stale fallback*.
  Introduced `_build_payload`. At that time `summary_paragraph` did not exist yet,
  so the omission was not a bug.
- `d4adf3962` — *PLAN-0103 W3: brief v4.2 collapsed summary + 6-section mandatory
  (**BP-624**)*. Added `summary_paragraph` to the schema, the main handler response
  path, and `_background_regen`. **Did not update the pre-gen worker's
  `_build_payload`.** ← this is the commit where the inconsistency was introduced.
- `git log -S "summary_paragraph" -- .../morning_brief_pregeneration_worker.py`
  returns **no commits** — the field has never been present in the worker.

So the "previously fixed" intro the user remembers was the BP-624 work; that fix
was only partially wired and the pre-gen-served path silently kept the pre-BP-624
(no-intro) behaviour. This matches the known compounding pattern *"audit/derived
return values must be persisted at every call site"* (MEMORY: `feedback_audit_
returned_value_persistence.md`).

---

## Recommendation

1. Add `summary_paragraph=result.get("summary_paragraph")` to
   `_build_payload` (one line — see above).
2. Add a unit-test assertion that `_build_payload` round-trips
   `summary_paragraph` (and ideally a parity test that the three builders emit the
   same field set, so a future field add can't regress one path again).
3. After deploy, evict/refresh the morning cache keys so users get the fixed
   payload immediately rather than waiting up to the next pre-gen interval.
