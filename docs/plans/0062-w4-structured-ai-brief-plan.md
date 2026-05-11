# PLAN-0062 — W4 Structured AI Brief (Tier 1, FR-T1-1)

> **PRD**: [PRD-0034 §3 FR-T1-1, §6 W4](../specs/0034-mvp-launch-readiness-program.md)
> **Status**: complete (all 5 waves done 2026-05-03)
> **Created**: 2026-05-03
> **Owner agent**: Staff engineer / TPM
> **Estimated effort**: ~3 dev-days (5 waves, 18 tasks; was 17 pre-audit, +1 for chat parity T-W4-E-05)
> **Critical path**: Wave A → Wave B → Wave C → Wave D → Wave E
> **Branch**: implement on top of `feat/content-ingestion-wave-a1` (or rebase from `main` at Wave A start)

---

## 1. Scope

PRD-0034 §6 W4 — **Structured AI Brief with deterministic schema and 100% citation rate**.

> Brief endpoint returns `{headline, sections[{title, bullets[{text, citations[{document_id, snippet, url}]}]}], confidence, generated_at}`. Frontend renders deterministically; every bullet is click-through to source. Acceptance: 100% of bullets have ≥1 citation; 0% of citations 404; rendering is identical across dashboard, instrument page, and chat.

**In scope**:
1. Extend the brief response schema with:
   - A new **`lead: str | None`** field (1-sentence-to-1-paragraph prose synthesis, 1–4 sentences, ≤600 chars, with inline `[cN]` markers — the analyst's "TL;DR" that may stand alone on compact surfaces). **Added 2026-05-03 per PRD-0034 §3 FR-T1-1 revision** that resolved OQ-5 by adding `lead` to the wire shape so the brief leads with prose synthesis (FinChat/AlphaSense pattern) rather than a pure bullet wall — prose is what the §2 "Sam the Analyst" persona reads first.
   - **Bullet-level citations** (`bullets[{text, citations[]}]`) — current schema is `bullets: list[str]` flat strings.
2. Add **`confidence`** field (top-level, 0–1 float).
3. Force the LLM prompt to emit a deterministic two-block output: a `## LEAD` block (1 sentence to 1 paragraph; the "1 paragraph" upper bound exists because large portfolios or active news days cannot be summarised in a single sentence) followed by `## DETAILS` sections of bulleted findings. Both `lead` and bullets carry `[cN]` citation markers resolved against the top-level `citations[]` list.
4. Implement the **citation→source URL/snippet resolution** so every bullet carries `{document_id, snippet, url}` and every `[cN]` marker in `lead` resolves to a `BriefCitation` in the shared top-level `citations[]` list.
5. **Single shared frontend `<StructuredBrief>` component** with three variants used consistently across all surfaces (revised 2026-05-03 per PRD-0034 §3 FR-T1-1):
   - **`compact`** (dashboard collapsed, instrument subheader, chat inline) → renders `headline + lead` only. **No section cards** — the lead paragraph IS the compact view, replacing the prior "show first section" rule which leaked an arbitrary section into compact surfaces.
   - **`full`** (dashboard expanded, instrument page, chat full) → renders `headline + lead + sections`.
   - **`inline`** (chat brief-kind messages) → renders `lead` (with optional headline) using inline citation chips/superscripts; no section card chrome (chat answers should look like prose, not dashboard widgets).
   `MorningBriefCard` (dashboard), `InstrumentBriefPanel` / `InstrumentAISubheader` (instrument page), and chat assistant `MessageBubble` all consume the same component with the appropriate variant. Chat parity is wired in Wave E by detecting brief-shaped payloads in assistant messages and rendering through `<StructuredBrief variant="inline">`. (Audit 2026-05-03 reverted prior scoping note that claimed chat already reused the brief render path — verified false; chat had no brief renderer prior to this plan.)
6. Tests:
   - Backend: schema/shape contract — every bullet has ≥1 citation at the Pydantic layer (server-side invariant + contract test); every `[cN]` marker in `lead` resolves to a `BriefCitation` index in the top-level `citations[]` list (server-side invariant + contract test).
   - Backend: every citation URL is well-formed (parse-only check). **Runtime citation→snippet accuracy scoring is owned by PLAN-0063 W5-5-02** — not duplicated here. Note: PLAN-0063's LLM-judge must be updated to score per-`[cN]`-marker claim spans (lead sentence + enclosing bullet text), not whole-message text — coordination point flagged in PLAN-0063 audit 2026-05-03.
   - Frontend: deterministic render of fixed payload across all four surfaces (dashboard, instrument page, instrument subheader, chat) — citation-set parity (same set of resolvable hrefs) AND lead/headline-text parity. **Layout parity is explicitly relaxed to "consistent payload + variant-appropriate rendering"** because compact and inline variants are intentionally subsets of `full`.

**Out of scope** (cross-workstream boundaries):
- W1 (KG remediation) — relations populating the citation pool. W4 assumes the existing `BriefingContext.news_articles + recent_events + active_alerts` is the citation source. **W4 will work even with current near-empty KG**; W1 increases citation density but is not a precondition.
- W5 (hybrid retrieval & eval framework, PLAN-0063) — does not change the brief response shape. **Cross-plan boundary (revised 2026-05-03 audit)**: PLAN-0063 W5-5-02 OWNS the runtime LLM-judge citation-accuracy gate over the canonical 50-claim fixture and emits the `rag_citation_accuracy` gauge. PLAN-0062 W4-C-04 is **scoped to a schema/shape contract test only** — it validates Pydantic shape, citation-marker presence, and URL well-formedness (no runtime accuracy scoring, no LLM judge, no network calls). Both plans must reference the same fixture spec but ship at different layers (W4 = static shape, W5 = runtime accuracy). No code overlap.
- W6 (full-text search) — search has its own response shape; brief schema is unaffected. **No coordination required**.
- W9 (visible regression cleanup) — separate frontend bug-fix workstream. The structured brief frontend changes in W4 must NOT undo W9 fixes (`--muted-foreground` divergence, `/undefined` race). **Coordination point: keep `MorningBriefCard` token classes unchanged; only swap the body renderer.**
- LLM provider changes — out of scope.
- Streaming the brief — out of scope (current `await uc.execute_public_*()` collects then returns; PRD does not require streaming for W4).

**Cross-workstream dependencies (notes only — do NOT duplicate)**:
- Reads from `BriefingContextGatherer` outputs which are populated by S5/S6/S7. Empty KG (from W1) means fewer citations per bullet but does **not** break this workstream — the deterministic schema includes a `confidence` field that drops when citation density is low.
- The `<StructuredBrief>` component will be reused by the chat surface in a future workstream; W4 only ensures the API and component support it.

---

## 2. Codebase State Verification

Read on 2026-05-03 from `feat/content-ingestion-wave-a1` HEAD.

| PRD reference | Type | Service | Actual current state | PRD expected state | Delta |
|--|--|--|--|--|--|
| `PublicBriefingResponse.sections[].bullets` | Pydantic | S8 `services/rag-chat/src/rag_chat/api/schemas.py:118-119` | `bullets: list[str]` (flat string list, max 8) | `bullets: list[BriefBullet]` where `BriefBullet = {text, citations[]}` | **schema break** — additive on response shape but the inner type changes; need v1 alias path |
| `BriefSection` | Pydantic | S8 same file:109 | `BriefSection { title, bullets: list[str] }` | `BriefSection { title, bullets: list[BriefBullet] }` | breaking inner type |
| `confidence` | Pydantic | S8 — | absent | required field 0–1 float on `PublicBriefingResponse` | new field |
| `lead` | Pydantic | S8 — | absent (`narrative` carries an unstructured markdown blob; v2.2 prompt emits a `## SUMMARY` 1–2 sentences but the field is mapped into `headline` losing the second sentence) | `lead: str \| None = Field(default=None, max_length=600)` on `PublicBriefingResponse` and `BriefingResponse` — 1 sentence to 1 paragraph (1–4 sentences) prose synthesis with inline `[cN]` markers | new field (added 2026-05-03 per PRD-0034 §3 FR-T1-1 revision) |
| `_parse_sections_from_markdown` | function | S8 `application/use_cases/generate_briefing.py:138-205` | parses headings + raw bullet strings | must emit `BriefBullet` with citations | logic rewrite |
| `MORNING_BRIEFING` prompt | template | `libs/prompts/src/prompts/briefing/morning.py` | emits `## SUMMARY` + `## DETAILS` markdown | must emit citation markers `[c1]` `[c2]` per bullet OR JSON block | prompt update + parser update |
| `INSTRUMENT_BRIEFING` prompt | template | `libs/prompts/src/prompts/briefing/instrument.py` | similar markdown only | same change | prompt update + parser update |
| `_build_citations` | function | S8 same file:871-917 | builds top-level `citations[]` list of `{source_type, source_id, title, url}` | must remain (back-compat) AND each citation must surface `snippet` field | add `snippet` field + extend |
| `BriefingCitation` | TS interface | `apps/worldview-web/types/api.ts:1080-1088` | `{source_type, source_id, title, url}` | `{document_id, snippet, url}` per PRD spec — but must support both shapes for back-compat | add fields, do not remove |
| `BriefSection` | TS interface | `apps/worldview-web/types/api.ts:1125-1128` | `{title, bullets: string[]}` | `{title, bullets: BriefBullet[]}` | breaking inner change |
| `MorningBriefCard.tsx` | component | `apps/worldview-web/components/dashboard/` | renders `narrative` markdown via `ReactMarkdown` | must render `sections[].bullets[].text` deterministically with click-through citations | rewrite body |
| `InstrumentBriefPanel.tsx` / `InstrumentAISubheader.tsx` | components | `apps/worldview-web/components/instrument/` | similar markdown render | swap to `<StructuredBrief>` | rewrite body |
| `<StructuredBrief>` shared component | component | — | does not exist | new shared component | new file |
| S9 `/v1/briefings/morning` proxy | route | `services/api-gateway/src/api_gateway/routes/proxy.py:1660` | exists, raw passthrough | unchanged (proxy is shape-agnostic) | none — verify |
| S9 `/v1/briefings/instrument/{entity_id}` proxy | route | same file:1681 | exists, raw passthrough | unchanged | none — verify |
| Brief contract test | test | `services/rag-chat/tests/contract/` | none for brief shape | new — assert citation accuracy + JSON schema | new file |
| 50-claim fixture (PRD §11) | test asset | `services/rag-chat/tests/contract/fixtures/` | does not exist | citation-accuracy fixture (≥50 claims) | new |
| Frontend brief tests | test | `apps/worldview-web/__tests__/morning-brief-card.test.tsx`, `briefing.test.tsx` | snapshot of markdown render | rewrite for structured render + bullet click | rewrite |

**Deltas requiring migration**: none (no DB/Avro/Kafka changes — W4 is pure API + frontend).

**Tests that will break (must be updated in their wave)**:
- `services/rag-chat/tests/unit/application/test_generate_briefing*.py` — parser tests assert old shape.
- `services/rag-chat/tests/unit/api/test_public_briefings*.py` — schema validation tests.
- `apps/worldview-web/__tests__/morning-brief-card.test.tsx` — markdown render assertions.
- `apps/worldview-web/__tests__/briefing.test.tsx` — same.
- `apps/worldview-web/__tests__/instrument-detail.test.tsx` — instrument brief render.
- `apps/worldview-web/__tests__/dashboard.test.tsx` — brief integration in dashboard.
- `apps/worldview-web/__tests__/workspace.test.tsx` — `WorkspaceBriefWidget` if it consumes the brief.

**Schema back-compat strategy**:
The PRD's wire format is breaking (`bullets: list[str]` → `bullets: list[BriefBullet]`). This is a violation of **CLAUDE.md hard rule #11 (forward-compatible schemas — add fields with defaults, never remove/rename)** — explicitly acknowledged and mitigated. Strategy:
1. Bump response with both: keep old `summary`/`narrative` for unknown clients; add `headline`/`sections[].bullets[].text/citations` shape. Old clients ignore unknown fields, new clients ignore `narrative` — but they **must not see `bullets: list[str]`**.
2. **Decision**: ship a single coordinated commit that updates S8 + frontend together (see §3 release-window note). Cached entries in Valkey will deserialize against old shape — **must invalidate by versioning the cache key** (`briefing:morning:v2:{user_id}` instead of `briefing:morning:{user_id}`).
3. Confidence: required new field. Defaulting to 1.0 when LLM didn't emit a value (legacy fallback path).

---

## 3. Wave Decomposition

5 waves. Each wave leaves the codebase green. Total ≈18 tasks (was 17; +1 for T-W4-E-05 chat parity, audit 2026-05-03 B-2 fix).

| Wave | Title | Layer | Effort | Depends on |
|--|--|--|--|--|
| A | Backend domain + schema | domain + Pydantic | 60 min | none |
| B | Backend prompt + parser + citation resolver | application | 90 min | A |
| C | Backend integration + cache key bump + tests | API + integration | 75 min | B |
| D | Frontend types + shared `<StructuredBrief>` component | UI | 75 min | C |
| E | Frontend integration (4 surfaces: dashboard + instrument + subheader + chat) + tests + parity audit | UI integration | 90 min | D |

**Release-window discipline (revised 2026-05-03 audit, I-2)**: The inner-type swap `bullets: list[str]` → `list[BriefBullet]` is a wire-format break, mitigated by the `v2` cache-key bump. To avoid a window where a deployed backend serves `BriefBullet[]` to a still-deployed legacy frontend (which would crash on `bullets[i].text` access against the old `string` shape), **a single coordinated frontend+backend release is mandatory**. Concretely: this branch shall NOT merge to main until Waves A–E are all green, and the merge SHALL be a single coordinated release (squash-merge optional but recommended; if split into 2 PRs, frontend PR must merge within the same deploy window, before backend rolls out to any environment serving real frontend traffic).

---

## 4. Cross-Cutting Concerns

- **Contract changes**: `PublicBriefingResponse` Pydantic model + matching TS interface. Versioned via Valkey cache-key bump (`v2`).
- **No DB / Avro / Kafka** — pure API + frontend.
- **Configuration**: no new env vars required (the citation 404 verification budget is hardcoded in test fixture).
- **Documentation**: `docs/services/rag-chat.md` brief section; `docs/services/api-gateway.md` brief routes (no signature change but document the new schema); `apps/worldview-web` brief component docstring; `docs/ui/DESIGN_SYSTEM.md` if `<StructuredBrief>` introduces new tokens (it should not — reuse existing).

---

## 5. Risk Assessment

| Risk | Severity | Mitigation |
|--|--|--|
| LLM does not honor citation-marker contract → bullets miss citations | HIGH | (a) prompt JSON-emit fallback on parser failure; (b) post-hoc backfill: if `bullet.citations` is empty, attach the highest-trust citation from the surrounding section. **100% citation rate is enforced server-side, not by LLM compliance.** |
| Cached briefs in Valkey carry old shape → frontend crashes | MEDIUM | bump cache key prefix to `briefing:*:v2:*`. Old keys orphaned, expire naturally on 24h TTL. |
| `<StructuredBrief>` divergent rendering across 4 surfaces (dashboard + instrument panel + instrument subheader + chat) | MEDIUM | single component, all callers pass identical props; visual snapshot/parity test gates parity (Wave E T-W4-E-04). |
| Frontend tests broken in 2 PRs (one for backend shape, one for frontend) | HIGH | **Mandatory**: all waves on a single branch; NO merge to main until Waves A–E are green AND a coordinated single release is opened (see §3 release-window discipline, audit 2026-05-03 I-2). Squash-merge optional but recommended. If split into 2 PRs, frontend PR MUST land within the same deploy window as backend. |
| Confidence score is gameable / meaningless | LOW | Use deterministic composite formula (revised 2026-05-03): `confidence = min(1.0, composite_density * coverage_factor)` where `composite_density = 0.4 * lead_density + 0.6 * bullet_density`, `lead_density = 1.0 if (lead and lead_citations) else 0.0`, `bullet_density = bullets_with_citations / total_bullets`, and `coverage_factor = min(1.0, total_citations / 8.0)`. Documented in Wave B-04. The composite weighting reflects that the lead is the analyst's primary surface — losing it tanks confidence even if bullets are dense. |
| LLM does not honor the lead-block format | MEDIUM | Parser is tolerant: missing `## LEAD` header → `lead=None`, sections still parse from `## DETAILS` block. Missing `---` divider → entire output treated as details, `lead=None`. Lead with no citations → `lead=None` (uncited lead violates PRD acceptance b). Result is a degraded but valid brief with `confidence` dropping to ≤0.6 (composite formula), which surfaces an amber "Limited source coverage" banner to the analyst. **No 500s, no broken UX** — just a less useful brief. |
| Lead exceeds 600 chars on long-active days | LOW | Parser truncates at the last sentence boundary `.!?` ≤600 (never mid-word). The Pydantic `max_length=600` is the hard server-side guard; the parser's truncation is the soft client-side guard so the LLM's verbose output still lands as a valid lead instead of a 422. |
| OQ-5 (exact JSON Schema deferred) | MEDIUM | Plan derives schema from FR-T1-1 verbatim. If user later issues PRD-0035 with a different shape, this becomes a refactor. **Surface this as an open question in handoff.** |

---

## 6. Waves

(See following sections.)

---

### Wave A: Backend domain + schema (additive types)

**Goal**: Add `BriefBullet`, `BriefCitation` (extended), and `confidence` field to the brief response shape. No prompt or parser changes yet — schema-first so subsequent waves compile against the new types.
**Depends on**: none
**Estimated effort**: 60 min
**Architecture layer**: domain + API schema

#### Pre-read
- `services/rag-chat/src/rag_chat/api/schemas.py` lines 100–180 (existing `BriefSection`, `PublicBriefingResponse`)
- `apps/worldview-web/types/api.ts` lines 1080–1130 (existing `BriefingCitation`, `BriefSection`, `BriefingResponse`)
- PRD-0034 §3 FR-T1-1 (the exact wire shape required)

#### Tasks

##### T-W4-A-01: Add `BriefBullet` + `BriefCitation` Pydantic models in S8
**Type**: schema
**depends_on**: none
**blocks**: T-W4-A-02, T-W4-B-01
**Target files**:
- `services/rag-chat/src/rag_chat/api/schemas.py` (modify)
**PRD reference**: §3 FR-T1-1

**What to build**:
Add two new Pydantic models above `BriefSection`. `BriefCitation` carries the document_id/snippet/url triple required by the PRD. `BriefBullet` is `{text, citations: list[BriefCitation]}`. These are the leaf types of the structured brief.

**Entities / Components**:
- **Name**: `BriefCitation`
  - Purpose: One source-document reference attached to a bullet.
  - Key attributes:
    - `document_id: str` — UUID of the source (article/event/alert). Frozen, no alias.
    - `snippet: str = Field(..., max_length=400)` — quoted/synthesised excerpt that supports the bullet claim.
    - `url: str | None = Field(default=None)` — clickable URL when the source has one (None for events/alerts).
    - `source_type: Literal["article","event","alert"] = "article"` — preserved from existing `BriefingCitation` for back-compat.
    - `title: str | None = None` — preserved for back-compat with current `_build_citations`.
  - Invariants: `document_id` non-empty; `snippet` 1–400 chars.
- **Name**: `BriefBullet`
  - Purpose: One bullet inside a section.
  - Key attributes:
    - `text: str = Field(..., min_length=1, max_length=400)`
    - `citations: list[BriefCitation] = Field(..., min_length=1)` — **min_length=1 enforces the 100% citation rule at the schema layer**.

**Logic & Behavior**:
- Validation: `min_length=1` on `citations` is the hard gate — any bullet that reaches serialization without a citation will 500 (intentional; the use case must backfill before responding).

**Tests to write**:
| Test name | What it verifies | Type |
|---|---|---|
| `test_brief_citation_minimal_construction` | `BriefCitation(document_id="x", snippet="y")` round-trips through `model_dump()` | unit |
| `test_brief_citation_snippet_max_length_400` | snippet > 400 chars rejected | unit |
| `test_brief_bullet_requires_at_least_one_citation` | `BriefBullet(text="t", citations=[])` raises ValidationError | unit |
| `test_brief_bullet_text_max_length_400` | text > 400 chars rejected | unit |
| `test_brief_section_accepts_empty_bullets` | (audit 2026-05-03 I-5) `BriefSection(title="t", bullets=[])` constructs without ValidationError — required so `_backfill_uncited_bullets` can build intermediate states; empty sections are dropped by the wrapper before serialization | unit |
- Minimum new test count: 5
- Edge cases: empty citations list, snippet=400 (boundary), text length=1, `source_type="event"` URL=None

**Downstream test impact**:
- `libs/contracts/tests/test_avro_alignment.py` — none (no Avro touched)
- No existing tests reference `BriefBullet`/`BriefCitation` (new types) — only T-W4-A-02 will modify uses.

**Acceptance criteria**:
- [ ] Both classes added immediately above existing `BriefSection`.
- [ ] 4 new unit tests in `services/rag-chat/tests/unit/api/test_schemas_brief.py` (new file).
- [ ] `ruff check` and `mypy` clean on the file.

---

##### T-W4-A-02: Update `BriefSection` and `PublicBriefingResponse` to use new bullet shape + add `confidence`
**Type**: schema
**depends_on**: T-W4-A-01
**blocks**: T-W4-B-01, T-W4-D-01
**Target files**:
- `services/rag-chat/src/rag_chat/api/schemas.py` (modify lines 109–179)
**PRD reference**: §3 FR-T1-1

**What to build**:
Change `BriefSection.bullets` from `list[str]` to `list[BriefBullet]`. Add `confidence: float = Field(..., ge=0.0, le=1.0)` to `PublicBriefingResponse` and to internal `BriefingResponse`. Keep all other existing fields unchanged for back-compat with the email-digest path (`POST /internal/v1/briefings`) which doesn't yet need bullet-level citations — the internal path fills `confidence=1.0` and produces empty `sections`.

**Entities / Components**:
- **Name**: `BriefSection` (modify)
  - Key attributes (changed): `bullets: list[BriefBullet] = Field(..., min_length=0, max_length=8)` (was `list[str]` with `min_length=1`).
  - **Why relax `min_length=1` → `min_length=0`** (audit 2026-05-03, I-5): `_backfill_uncited_bullets` (T-W4-B-03) constructs intermediate `BriefSection` objects during its drop-uncited-bullets pass. If `min_length=1` remained, any intermediate state with all-uncited bullets would raise `ValidationError` at construction time, blocking the function from cleanly building its output. Relaxing to `min_length=0` lets the function construct freely and rely on a post-step that drops empty sections (the "100% citation guarantee" lives at the WRAPPER level, enforced via `BriefBullet.citations` `min_length=1` plus the backfill+drop pipeline).
  - **Hard invariant** (asserted in B-04 tests): every `BriefBullet` in any returned `BriefSection` has `len(citations) >= 1`. This is the real "100% citation rate" gate — kept at the leaf type, not the section type.
  - Other attributes unchanged: `title`
- **Name**: `PublicBriefingResponse` (modify)
  - Add: `confidence: float = Field(default=1.0, ge=0.0, le=1.0)` — defaulted (not required) to keep cached responses deserializable; T-W4-C-01 will populate it server-side.
  - Add: `lead: str | None = Field(default=None, max_length=600)` — **1-sentence-to-1-paragraph prose synthesis (1–4 sentences) with inline `[cN]` citation markers** that resolve against the top-level `citations[]` list. Defaulted to `None` so cached `v1` responses (which lack the field) deserialize cleanly into `v2` shape during the transition window before cache-key bump effective. Populated server-side by T-W4-B-04 from the parsed `## LEAD` block. `max_length=600` chosen to cap at ~4 dense sentences while keeping the lead scannable in a 3-line dashboard card; if the LLM emits a longer block the parser truncates at the last sentence boundary ≤600 (NOT mid-word).
  - Existing fields preserved: `narrative`, `risk_summary`, `citations`, `generated_at`, `cached`, `entity_id`, `summary`, `headline`, `sections`.
- **Name**: `BriefingResponse` (modify)
  - Add same `confidence` and `lead` fields with identical signatures and defaults.

**Logic & Behavior**:
- `BriefSection.bullets` switches inner type. Existing serializers in `_parse_sections_from_markdown` will need to construct `BriefBullet(text=..., citations=[...])`. **Out of scope for this task — that's T-W4-B-02.** This task only updates the schema.
- Defaulting `confidence=1.0` lets older response builders that don't compute it stay valid.

**Tests to write**:
| Test name | What it verifies | Type |
|---|---|---|
| `test_brief_section_with_brief_bullets` | `BriefSection(title="t", bullets=[BriefBullet(text="x", citations=[BriefCitation(document_id="d",snippet="s")])])` round-trips | unit |
| `test_public_briefing_response_confidence_default_1` | omitting `confidence` yields default 1.0 | unit |
| `test_public_briefing_response_confidence_out_of_range` | 1.1 raises ValidationError; -0.1 raises | unit |
| `test_briefing_response_confidence_default` | internal `BriefingResponse` defaults to 1.0 | unit |
- Minimum new test count: 4
- Edge cases: `confidence=0.0` (boundary), `confidence=1.0` (boundary), legacy payload without sections

**Downstream test impact** (mandatory):
- `services/rag-chat/tests/unit/api/test_*briefings*.py` — any test asserting `bullets: list[str]` will break. Update by constructing `BriefBullet` instances.
- `services/rag-chat/tests/unit/application/test_generate_briefing*.py` — `_parse_sections_from_markdown` tests assert old shape; they will be rewritten in T-W4-B-02.
- `services/rag-chat/tests/contract/test_brief_contract.py` (new in C-04) will be the canonical contract test.

**Acceptance criteria**:
- [ ] `BriefSection.bullets` typed as `list[BriefBullet]`.
- [ ] `confidence` added with default 1.0 on both `BriefingResponse` and `PublicBriefingResponse`.
- [ ] Existing schema tests adapted to construct `BriefBullet` objects (NOT deleted — fix in place per R19).
- [ ] `ruff` + `mypy` clean.

#### Validation Gate (Wave A)
- [ ] `ruff check services/rag-chat/src/rag_chat/api/schemas.py` clean
- [ ] `mypy services/rag-chat` clean
- [ ] `pytest services/rag-chat/tests/unit/api/test_schemas_brief.py -v` ≥8 new tests pass
- [ ] No prompt/parser/frontend changes (those are later waves)

#### Break Impact
| Broken file | Why it breaks | Fix required |
|---|---|---|
| `services/rag-chat/tests/unit/application/test_generate_briefing.py` (and any `test_generate_briefing_*.py` siblings) | Asserts on `bullets: list[str]` | Adapt assertions to `bullets: list[BriefBullet]`; reuse helper `_make_bullet(text, citations)` introduced in test file |
| `services/rag-chat/tests/unit/api/test_public_briefings.py` | constructs old `BriefSection` shape | construct `BriefBullet` objects with at least one `BriefCitation` |
| (frontend) — none yet, frontend types not touched until Wave D | — | — |

#### Regression Guardrails
- **CLAUDE.md hard rule #11 (forward-compatible schemas)**: Adding `confidence` with default 1.0 + accepting unknown fields is OK. The formal break is the inner type swap `bullets: list[str]` → `list[BriefBullet]`. **Mitigation**: Valkey cache-key bump `v1`→`v2` in Wave C prevents deserialization of stale cached objects; old keys orphan-expire on 24h TTL. Coordinated single-PR release (see §3) prevents mid-deploy frontend/backend skew.
- **BP-064** (FastAPI 204 status code): not applicable (we return 200).
- **BP-235** (httpx asyncio timeout): not applicable.

---

### Wave B: Backend prompt + parser + citation resolver

**Goal**: Make the LLM emit citation markers per bullet, parse them, and resolve them to `BriefCitation` objects with `document_id`/`snippet`/`url` populated. Compute deterministic `confidence`. Backfill any uncited bullet so the schema never rejects a brief at serialize time.
**Depends on**: Wave A complete
**Estimated effort**: 90 min
**Architecture layer**: application

#### Pre-read
- `libs/prompts/src/prompts/briefing/morning.py` (full file, 85 lines)
- `libs/prompts/src/prompts/briefing/instrument.py` (full file, 67 lines)
- `services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py` lines 138–205 (`_parse_sections_from_markdown`), 449–576 (`execute_public_morning`), 578–657 (`execute_public_instrument`), 871–917 (`_build_citations`)

#### Tasks

##### T-W4-B-01: Update `MORNING_BRIEFING` and `INSTRUMENT_BRIEFING` prompt templates to emit numbered citation markers per bullet
**Type**: impl
**depends_on**: T-W4-A-02
**blocks**: T-W4-B-02
**Target files**:
- `libs/prompts/src/prompts/briefing/morning.py` (modify)
- `libs/prompts/src/prompts/briefing/instrument.py` (modify)
- `libs/prompts/tests/test_knowledge_prompts.py` or new `test_briefing_prompts.py` (modify/create)
**PRD reference**: §3 FR-T1-1

**What to build**:
Both prompt templates already provide a list of context items (news articles, events, alerts) in the rendered context block. Modify both prompts to:
1. Number each context item explicitly in the `<context>` block (already done implicitly; we add a stable `[c1]`, `[c2]`, ... index).
2. **Emit a structured two-block output (revised 2026-05-03 per PRD-0034 §3 FR-T1-1 `lead` addition):**
   - **`## LEAD`** block — 1 sentence to 1 paragraph (1–4 sentences, ≤600 chars total). This is the prose synthesis the analyst reads first. It MUST include inline `[cN]` markers wherever a claim derives from a context item (e.g. "Three Fed signals [c1, c3] point to a hawkish pivot, while ECB language softened [c4]."). The 1-paragraph upper bound exists explicitly because large portfolios or active news days cannot be summarised in one sentence. The lead must NOT be a bulleted list and must NOT contain heading characters (`#`, `*`, `-` at line start) — pure prose only.
   - Then a literal `---` divider.
   - Then **`## DETAILS`** block — the existing four sections (Market Overview / Portfolio Impact / Key News / Active Alerts & Signals for morning; the five sections for instrument), each section title as `### `, each finding as a `-` bullet ending with at least one `[cN]` marker.
3. Instruct the LLM to append `[cN]` (or `[cN, cM]`) markers at the end of every bullet to indicate which context items support it.
4. Add a hard rule: **every bullet must end with at least one `[cN]` marker, AND the lead must contain at least one `[cN]` marker (or be omitted entirely)**. If the LLM cannot find supporting sources for a bullet, it must omit the bullet rather than emit it uncited. If the LLM cannot find supporting sources for the entire context, it MAY omit the lead and emit only details — the parser handles `lead=None` gracefully.
5. **Length discipline tightened (revised 2026-05-03)**: cap details to ≤4 sections × ≤4 bullets × ≤140 chars per bullet (was 4×8×400). The earlier limits permitted a 25k-char brief; the revised limits target a scan-friendly card. Total brief target: 300–800 words across `lead` + sections (was 500–1000 in v2.2).

The change is to the prompt _instructions_ — the rendered `news_context`/`events_context`/`alerts_context` strings emitted by `_format_news` etc. must also be updated in T-W4-B-02 to prefix items with `[c1]`/`[c2]` markers so the LLM has stable indices to cite.

**Logic & Behavior**:
- Markers use square brackets to follow the existing chat-citation convention.
- Markers are 1-indexed across the union of `news_articles + recent_events + active_alerts` in the order the context is rendered (deterministic).
- Add a fallback example in the prompt showing the desired output:
  ```
  ## LEAD
  Tech sector opened soft on the back of CPI surprise [c1] and renewed semis-export friction [c4]; portfolio NVDA exposure flagged for review.

  ---

  ## DETAILS
  ### Market Overview
  - SPX -0.6% pre-market on hot CPI [c1]
  - 10Y yield +8bps [c2]
  ...
  ```

**Tests to write**:
| Test name | What it verifies | Type |
|---|---|---|
| `test_morning_briefing_prompt_renders_citation_instructions` | rendered prompt contains the `[cN]` instruction string | unit |
| `test_instrument_briefing_prompt_renders_citation_instructions` | same for instrument | unit |
- Minimum new test count: 2

**Downstream test impact**:
- `libs/prompts/tests/test_knowledge_prompts.py` (or wherever briefing prompts are tested) — existing render tests that snapshot the prompt body must be updated for the new instruction text.

**Acceptance criteria**:
- [ ] Both prompt templates contain the new instruction block.
- [ ] Existing prompt snapshot tests updated.

---

##### T-W4-B-02: Rewrite `_parse_sections_from_markdown` to emit `BriefBullet` with `[cN]` extracted citations
**Type**: impl
**depends_on**: T-W4-A-02, T-W4-B-01
**blocks**: T-W4-B-03, T-W4-B-04
**Target files**:
- `services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py` (modify lines 138–205 and helpers)
**PRD reference**: §3 FR-T1-1

**What to build**:
Replace `_parse_sections_from_markdown` with a parser that:
1. **Splits the LLM output on the literal `---` divider into a `lead_block` (everything before the divider, with the leading `## LEAD` header stripped) and a `details_block` (everything after, including the `## DETAILS` header).** If no divider is present, treat the whole output as `details_block` and return `lead=None` (degraded but valid).
2. **Parses the lead block** as a single prose string: strip the `## LEAD` header line, collapse internal whitespace, validate `1 ≤ len(lead) ≤ 600` (truncate at the last sentence boundary `.!?` ≤600 if longer; never mid-word), and extract inline `[cN]`/`[cN, cM]` markers (which remain in the prose for the renderer to display, NOT stripped — the prose `lead` keeps `[cN]` text inline so the frontend can render numbered superscripts in place). Resolve markers to `list[BriefCitation]` indices for return as `lead_citations`.
3. Recognises `## ` / `### ` / bold-only section headings in the details block (existing behaviour).
4. Recognises bullet lines `- `, `* `, `• ` in the details block.
5. Extracts trailing `[cN]` or `[cN, cM, cK]` markers from each bullet via regex `_BULLET_CITE_RE = re.compile(r"\s*\[c(\d+(?:\s*,\s*c?\d+)*)\]\s*$")`. **Bullet markers ARE stripped from the bullet text** (they render as separate chips in the UI) — this differs from the lead, where markers stay inline.
6. Returns `(lead, lead_citations, sections)` where `sections: list[BriefSection]` matches the existing shape and `lead: str | None`, `lead_citations: list[BriefCitation]`.
7. If the parsed bullet has no markers OR markers point to out-of-range indices, leave `citations=[]` for now — backfill happens in T-W4-B-03. If the lead has no markers OR all markers point out-of-range, set `lead = None` (do NOT keep an uncited lead — violates the lead-citation invariant from PRD-0034 §3 FR-T1-1 acceptance (b)).

**Entities / Components**:
- New helper signature:
  ```python
  def _parse_sections_with_citations(
      markdown: str,
      context_citations: list[BriefCitation],
  ) -> tuple[str | None, list[BriefCitation], list[BriefSection]]: ...
  ```
- Existing `_parse_sections_from_markdown` removed (R19 — fix in place, not deleted: rename to mark intent and update all call sites).

**Logic & Behavior**:
- `[cN]` marker → 1-indexed lookup into `context_citations` (`citations.append(context_citations[N-1])`).
- Out-of-range or invalid → silently dropped; bullet's `citations` list may end up empty (handled by T-W4-B-03).
- Cap bullets per section at 8 (existing rule), title at 120 chars (existing rule).

**Tests to write** (add to existing `tests/unit/application/test_generate_briefing.py`):
| Test name | What it verifies | Type |
|---|---|---|
| `test_parse_sections_extracts_single_citation` | `- text [c1]` → bullet with 1 citation | unit |
| `test_parse_sections_extracts_multiple_citations` | `- text [c1, c2, c3]` → bullet with 3 citations | unit |
| `test_parse_sections_strips_markers_from_text` | bullet text has no `[cN]` suffix after parse | unit |
| `test_parse_sections_out_of_range_marker_dropped` | `[c99]` with 3 context citations → bullet citations=[] | unit |
| `test_parse_sections_no_marker_yields_empty_citations` | bullet with no marker → citations=[] | unit |
| `test_parse_sections_handles_whitespace_in_marker` | `[c1 ,  c2]` parses correctly | unit |
| `test_parse_sections_returns_empty_for_blank_markdown` | "" → (None, [], []) | unit |
| `test_parse_lead_extracts_paragraph_and_citations` | (lead) `## LEAD\n\nFoo [c1] bar [c2].\n\n---\n\n## DETAILS\n...` → lead="Foo [c1] bar [c2].", lead_citations resolves to ctx[0],ctx[1] | unit |
| `test_parse_lead_keeps_inline_markers_in_text` | (lead) parsed lead string still contains `[c1]` text — markers NOT stripped (renderer handles them) | unit |
| `test_parse_lead_truncates_at_sentence_boundary_above_600` | (lead) 800-char lead truncated at last `.` ≤600, never mid-word | unit |
| `test_parse_lead_returns_none_when_uncited` | (lead) lead with no `[cN]` markers → lead=None (invariant: no uncited lead) | unit |
| `test_parse_lead_returns_none_when_all_markers_out_of_range` | (lead) lead with only `[c99]` against 3 ctx citations → lead=None | unit |
| `test_parse_lead_returns_none_when_no_lead_block` | (lead) markdown with no `---` divider → lead=None, sections still parsed | unit |
| `test_parse_lead_rejects_bullet_or_heading_chars` | (lead) lead block containing `- ` or `# ` line → ValueError or fall-back lead=None | unit |
- Minimum new test count: 14 (was 7; +7 for lead extraction & invariants)
- Edge cases: nested brackets in body, escaped `\[c1\]`, marker on heading line ignored, lead with only `## LEAD` header and empty body, lead with markers spanning a sentence boundary.

**Downstream test impact**:
- All existing `_parse_sections_from_markdown` tests in `test_generate_briefing.py` need to be updated or replaced — the function is renamed and signature changed. **R19**: update assertions, do not delete tests.

**Acceptance criteria**:
- [ ] New helper exported from module.
- [ ] All call sites updated to new signature.
- [ ] 7+ new unit tests, all old parser tests adapted.

---

##### T-W4-B-03: Add `_backfill_uncited_bullets` and citation `snippet` materialisation
**Type**: impl
**depends_on**: T-W4-B-02
**blocks**: T-W4-B-04
**Target files**:
- `services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py` (modify, add helpers)
**PRD reference**: §3 FR-T1-1 acceptance criterion: "100% of bullets have ≥1 citation"

**What to build**:
Two helpers:

1. `_materialize_brief_citations(ctx: BriefingContext) -> list[BriefCitation]` — walks the same data as `_build_citations` and produces a list typed as `BriefCitation` (with `snippet` populated). For articles, snippet = first 240 chars of the article title + " — " + the first 160 chars of the article summary if available, else the title alone. For events, snippet = first 240 chars of `event_text`. For alerts, snippet = `payload.get("message", "")[:240]`. Snippet must be non-empty (≤400 chars per schema).

2. `_backfill_uncited_bullets(sections: list[BriefSection], context_citations: list[BriefCitation]) -> list[BriefSection]` — for any bullet with empty `citations`, attach the highest-trust citation from the section (heuristic: the first article citation in the section if any are present; otherwise the first event; otherwise the first alert; otherwise the first global context citation). If `context_citations` is also empty, **drop the bullet entirely** (cannot satisfy the 100% rule). If the section becomes empty after dropping, drop the section.

**Construction discipline** (audit 2026-05-03, I-5): the function MUST build new `BriefSection` and `BriefBullet` objects via list comprehensions / explicit constructor calls — Pydantic frozen models do not support in-place mutation. Order of operations: (a) for each section, build a NEW list of `BriefBullet` instances filtering or backfilling each bullet; (b) construct a new `BriefSection(title=..., bullets=<new_list>)`; (c) drop sections whose new `bullets` list is empty. Because `BriefSection.bullets` is `min_length=0` (per A-02 fix for I-5), the intermediate construct-then-drop is safe. Because `BriefBullet.citations` remains `min_length=1`, NO `BriefBullet` with empty citations can ever be constructed — the function must FILTER such bullets out BEFORE constructing them, never construct one and then "fix" it.

**Entities / Components**:
- Both are pure functions; no new classes.

**Logic & Behavior**:
- Snippet truncation: 240/160/240 limits chosen so the combined string respects `BriefCitation.snippet` max=400 with margin.
- Backfill heuristic order: article > event > alert (matches typical user trust ordering).
- Drop-on-empty is documented in the function's docstring as the "100% citation guarantee" enforcement.

**Tests to write**:
| Test name | What it verifies | Type |
|---|---|---|
| `test_materialize_citations_populates_snippet_from_article` | article citation snippet contains title prefix | unit |
| `test_materialize_citations_handles_missing_summary` | summary=None → snippet falls back to title only | unit |
| `test_materialize_citations_event_snippet_truncated` | event_text > 240 chars truncated | unit |
| `test_backfill_uncited_bullets_attaches_first_article` | uncited bullet gets first article citation | unit |
| `test_backfill_drops_bullet_when_no_citations_available` | bullet dropped when context_citations empty | unit |
| `test_backfill_drops_empty_section` | section with all bullets dropped is removed | unit |
| `test_backfill_preserves_already_cited_bullets` | bullets with non-empty citations untouched | unit |
| `test_backfill_never_constructs_brief_bullet_with_empty_citations` | (audit 2026-05-03 I-5) attempting `BriefBullet(text="x", citations=[])` directly raises ValidationError — guards the leaf invariant | unit |
- Minimum new test count: 8

**Acceptance criteria**:
- [ ] No bullet in any output of `_backfill_uncited_bullets` ever has `citations=[]`.
- [ ] Snippet always 1–400 chars.

---

##### T-W4-B-04: Compute `confidence` and wire structured response in `execute_public_morning` and `execute_public_instrument`
**Type**: impl
**depends_on**: T-W4-B-03
**blocks**: T-W4-C-01
**Target files**:
- `services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py` (modify the two `execute_public_*` methods)
**PRD reference**: §3 FR-T1-1, §5 risk-row "Confidence is gameable"

**What to build**:
In both `execute_public_morning` and `execute_public_instrument`:
1. After streaming the LLM output, build `context_citations = _materialize_brief_citations(ctx)`.
2. Replace the existing `_parse_sections_from_markdown(narrative)` call with `lead, lead_citations, sections = _parse_sections_with_citations(narrative, context_citations)` (revised 2026-05-03 — parser now returns a 3-tuple).
3. Run `_backfill_uncited_bullets(sections, context_citations)`.
4. Compute confidence — **revised 2026-05-03 to factor in `lead` citation density** so the formula reflects the analyst's actual surface (the lead is what they read first):
   ```python
   total_bullets = sum(len(s.bullets) for s in sections)
   cited_bullets = sum(1 for s in sections for b in s.bullets if b.citations)
   bullet_density = (cited_bullets / total_bullets) if total_bullets else 0.0

   # Lead density: 1.0 if lead is present and has ≥1 resolved citation; 0.0 if absent.
   # Rationale: under FR-T1-1 acceptance (b) the lead must contain ≥1 resolvable [cN].
   # If lead=None (degraded), the brief loses its synthesis surface — confidence
   # drops accordingly so the frontend can show a "Limited synthesis" hint.
   lead_density = 1.0 if (lead and lead_citations) else 0.0

   # Weighted average: lead is 40% of confidence, bullets are 60%. The lead is
   # high-value-per-character (it's the analyst's TL;DR) so it's weighted heavier
   # per unit than bullets, but bullets carry the bulk of the citation surface.
   composite_density = (0.4 * lead_density) + (0.6 * bullet_density)

   total_citations = sum(len(b.citations) for s in sections for b in s.bullets) + len(lead_citations)
   coverage_factor = min(1.0, total_citations / 8.0)  # 8 = ~well-cited brief; F-W4-1 tunable
   confidence = round(min(1.0, composite_density * coverage_factor), 4)
   ```
5. Return dict now also includes `confidence: float` AND **`lead: str | None`** (revised 2026-05-03). Existing keys (`content`, `summary`, `headline`, `sections`, `risk_summary`, `entity_mentions`, `citations`, `generated_at`) preserved. The route layer (T-W4-C-01) propagates `lead` to the response JSON.

**Tests to write**:
| Test name | What it verifies | Type |
|---|---|---|
| `test_execute_public_morning_returns_confidence` | dict has `confidence` key, 0 ≤ value ≤ 1 | unit |
| `test_execute_public_morning_returns_lead` | dict has `lead` key (str or None) | unit |
| `test_execute_public_morning_confidence_zero_on_empty_sections_and_no_lead` | empty sections AND lead=None → confidence=0.0 | unit |
| `test_execute_public_morning_confidence_drops_when_lead_missing` | sections fully cited but lead=None → confidence ≤ 0.6 (only bullet_density × coverage contributes) | unit |
| `test_execute_public_morning_confidence_one_on_dense_citations_and_lead` | 4 sections × 4 bullets all cited, lead present with citation, ≥8 citations → 1.0 | unit |
| `test_execute_public_morning_all_bullets_have_citations` | post-backfill invariant: every bullet has ≥1 citation | unit |
| `test_execute_public_morning_lead_invariant` | (lead) if dict[`lead`] is not None, the parsed lead contains ≥1 `[cN]` marker resolving in `citations[]` | unit |
| `test_execute_public_instrument_returns_confidence` | same for instrument | unit |
| `test_execute_public_instrument_returns_lead` | same for instrument | unit |
| `test_execute_public_instrument_all_bullets_have_citations` | invariant on instrument path | unit |
| `test_execute_public_instrument_lead_invariant` | same as morning lead invariant | unit |
- Minimum new test count: 11 (was 6; +5 for lead surface)

**Acceptance criteria**:
- [ ] Both methods return `confidence: float`.
- [ ] **Server-side invariant** (asserted in tests): for any return value, `all(b.citations for s in result["sections"] for b in s.bullets)` is True.
- [ ] No regression in existing `execute_public_*` tests (adapted, not deleted).

#### Validation Gate (Wave B)
- [ ] `ruff` clean on modified files
- [ ] `mypy services/rag-chat` clean
- [ ] `mypy libs/prompts` clean
- [ ] `pytest services/rag-chat/tests/unit/application/test_generate_briefing*.py -v` all pass with ≥20 new tests added cumulatively in this wave
- [ ] `pytest libs/prompts/tests -v` all pass
- [ ] No frontend changes (Wave D)

#### Break Impact
| Broken file | Why it breaks | Fix required |
|---|---|---|
| `libs/prompts/tests/test_knowledge_prompts.py` (or briefing-prompt tests) | New instruction text in prompt | update snapshot/string-equality assertions |
| `services/rag-chat/tests/unit/application/test_generate_briefing*.py` | parser renamed + signature changed; sections shape changed | adapt all `_parse_sections_from_markdown` calls to `_parse_sections_with_citations`; update assertions to `BriefBullet` |
| `services/rag-chat/tests/unit/api/test_public_briefings.py` (mocked `execute_public_*`) | mocked return shape needs `confidence` key | update mock fixtures to include `"confidence": 0.9` |

#### Regression Guardrails
- **BP-180** (asyncpg `IS NULL` ambiguity in CTEs): not applicable (no SQL).
- **BP-235** (httpx asyncio timeout): not applicable (no external HTTP).
- **CLAUDE.md hard rule #11 (forward-compatible schemas)**: the inner-type swap `bullets: list[str]` → `list[BriefBullet]` is mitigated by Wave C cache-key bump (v1→v2) and the coordinated single-PR release discipline (§3).
- **MEMORY: Audit return values must be persisted** — `confidence` is computed and **must be returned** in the result dict, not just logged. The route layer (`public_briefings.py`) must propagate it to the response JSON. Write a test (in C-02) that asserts the route response contains `confidence`.
- **MEMORY: Prompt input vs lookup mismatch** — the prompt instruction (Wave B-01) tells the LLM to use `[c1]`/`[c2]` markers; the parser (Wave B-02) must read from the SAME index source the prompt was given. Concretely: the order of items rendered in `_format_news` + `_format_events` + `_format_alerts` MUST match the order of `_materialize_brief_citations(ctx)`. Add an explicit unit test asserting this index-alignment invariant.


---

### Wave C: Backend integration + cache key bump + contract tests

**Goal**: wire the new shape through the route layer, bump Valkey cache key to `v2`, add a contract test that proves "100% citation rate" and "0% 404" against a 50-claim fixture, and confirm the S9 proxy passes the new fields through unchanged.
**Depends on**: Wave B complete
**Estimated effort**: 75 min
**Architecture layer**: API + integration

#### Pre-read
- `services/rag-chat/src/rag_chat/api/routes/public_briefings.py` (full file, ~240 lines)
- `services/api-gateway/src/api_gateway/routes/proxy.py` lines 1657–1701 (brief proxies)
- Existing contract test patterns: `services/rag-chat/tests/contract/` (read any file there for style)

#### Tasks

##### T-W4-C-01: Update `public_briefings.py` route to populate `confidence` and bump cache key to `v2`
**Type**: impl
**depends_on**: T-W4-B-04
**blocks**: T-W4-C-02, T-W4-C-04
**Target files**:
- `services/rag-chat/src/rag_chat/api/routes/public_briefings.py` (modify)
**PRD reference**: §3 FR-T1-1, §10 Failure Modes ("LLM provider down")

**What to build**:
1. Change `cache_key = f"briefing:morning:{user_id}"` → `cache_key = f"briefing:morning:v2:{user_id}"` (and same for instrument: `briefing:instrument:v2:{entity_id}:{user_id}`).
2. In both route handlers, propagate `confidence` AND `lead` from the use-case result dict into `response_data` (revised 2026-05-03):
   ```python
   "confidence": result.get("confidence", 1.0),
   "lead": result.get("lead"),  # str | None — see PRD-0034 §3 FR-T1-1 lead spec
   ```
3. Update the cached-response read path: when reading old `v1` keys would happen, the code now reads `v2` keys, so legacy entries are simply ignored and a fresh generation runs (orphaned `v1` keys expire on 24h TTL).
4. Add structured logging: `log.info("brief_response_built", confidence=confidence, lead_present=lead is not None, lead_chars=len(lead or ""), sections=len(sections), total_citations=...)`.

**Tests to write**:
| Test name | What it verifies | Type |
|---|---|---|
| `test_morning_route_emits_v2_cache_key` | Valkey mock receives key starting with `briefing:morning:v2:` | unit |
| `test_morning_route_propagates_confidence` | response JSON contains `confidence` key from UC | unit |
| `test_morning_route_confidence_default_when_missing_from_uc` | UC returns dict without `confidence` → response has 1.0 | unit |
| `test_morning_route_propagates_lead` | (lead) UC returns `{"lead": "Foo [c1] bar."}` → response JSON has `lead` matching | unit |
| `test_morning_route_lead_null_when_uc_omits` | (lead) UC omits `lead` → response JSON has `lead: null` (not missing key) | unit |
| `test_instrument_route_emits_v2_cache_key` | same for instrument | unit |
| `test_instrument_route_propagates_confidence` | same | unit |
| `test_instrument_route_propagates_lead` | (lead) same lead-propagation invariant on instrument route | unit |
- Minimum new test count: 8 (was 5; +3 for lead)

**Acceptance criteria**:
- [ ] `grep "briefing:morning:" services/rag-chat/src/rag_chat/api/routes/public_briefings.py` returns only `v2` references.
- [ ] `confidence` always in response JSON.
- [ ] `lead` always in response JSON (may be `null`); never missing the key (frontend `lead?: string | null` requires the key to be present even when null, per TS exactness).

---

##### T-W4-C-02: Add `snippet` field to `BriefingCitation` schema and update `_build_citations` to populate it
**Type**: schema
**depends_on**: T-W4-A-02
**blocks**: T-W4-C-04
**Target files**:
- `services/rag-chat/src/rag_chat/api/schemas.py` (modify existing `BriefingCitation` if defined there; otherwise the schema lives implicitly as `dict[str, Any]` — formalise it)
- `services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py` `_build_citations` (modify to include `snippet`)
**PRD reference**: §3 FR-T1-1

**What to build**:
The top-level `citations` list on `PublicBriefingResponse` is currently `list[dict[str, Any]]`. Formalise it as `list[BriefCitation]` (reusing the type from Wave A). Update `_build_citations` to return dicts that satisfy `BriefCitation` shape: include `document_id` (= existing `source_id`), `snippet` (computed by `_materialize_brief_citations` reuse), `url`, and keep `source_type` + `title` for back-compat.

**Logic**:
- The `citations` list at the top of `PublicBriefingResponse` and the per-bullet citations list are now both `list[BriefCitation]`. This unifies the shape.
- Migration concern: existing serialized response has `source_id`; the PRD wants `document_id`. Solution: `BriefCitation` defines `document_id` as the canonical field name and accepts `source_id` as an alias via Pydantic `Field(alias="source_id")` if migration of internal callers is too costly. **Decision: alias-in for back-compat. Internal `_build_citations` emits `document_id` going forward.**

**Tests to write**:
| Test name | What it verifies | Type |
|---|---|---|
| `test_build_citations_emits_document_id_field` | resulting dicts have `document_id` populated | unit |
| `test_build_citations_emits_snippet_for_each` | every citation has non-empty snippet ≤400 chars | unit |
| `test_brief_citation_alias_accepts_source_id` | constructing from `{"source_id": "x", "snippet": "y"}` works (back-compat) | unit |
- Minimum new test count: 3

**Acceptance criteria**:
- [ ] All `_build_citations` callers continue to work (legacy email digest path).
- [ ] Top-level `PublicBriefingResponse.citations` is typed `list[BriefCitation]`.

---

##### T-W4-C-03: Verify S9 proxy is shape-agnostic (no code change expected; document)
**Type**: docs
**depends_on**: T-W4-C-01
**blocks**: none
**Target files**:
- `docs/services/api-gateway.md` (small update to brief routes section)
**PRD reference**: §3 FR-T1-1

**What to build**:
Read `services/api-gateway/src/api_gateway/routes/proxy.py:1660-1700`. Both routes use `Response(content=resp.content, ...)` which is byte-passthrough — no Pydantic deserialization. **No code change needed**. Document this in `docs/services/api-gateway.md`: the brief proxies are forward-compatible with any S8 schema bump because they pass bytes through.

**Tests to write**: none (documentation only).

**Acceptance criteria**:
- [ ] `docs/services/api-gateway.md` brief section notes the byte-passthrough behaviour and the `confidence` field.

---

##### T-W4-C-04: Brief schema/shape contract test (NOT runtime accuracy — that ships in PLAN-0063 W5-5-02)
**Type**: test
**depends_on**: T-W4-C-01, T-W4-C-02
**blocks**: T-W4-D-01
**Target files**:
- `services/rag-chat/tests/contract/test_brief_contract.py` (new)
- `services/rag-chat/tests/contract/fixtures/brief_50_claims.json` (new)
**PRD reference**: §11 Test Strategy "Citation accuracy" — **shape layer only**; runtime LLM-judge scoring lives in PLAN-0063 W5-5-02.

**Scope (revised 2026-05-03 audit, B-1 resolution)**:
This task is intentionally narrowed to a **schema/shape contract test**. It does NOT score citation→snippet relevance and does NOT emit `rag_citation_accuracy`. PLAN-0063 W5-5-02 owns the runtime accuracy gate (LLM-as-judge weekly cron over the same fixture). Two layers, two test purposes, one shared fixture spec.

**What this task verifies**:
1. Pydantic shape contract — `PublicBriefingResponse.model_validate(...)` round-trips on every fixture-derived response.
2. Citation-marker presence — every bullet in every fixture-driven brief has `len(citations) >= 1` after parser + backfill.
3. URL well-formedness — every citation URL parses cleanly via `urllib.parse.urlparse` (scheme + netloc non-empty). **No network probes.** A live-probe variant gated by `RUN_LIVE_404_PROBE=1` env can run in nightly QA but is NOT this task.
4. `confidence ∈ [0.0, 1.0]` for every fixture.

**What this task explicitly does NOT verify**:
- Whether the citation snippet actually supports the bullet claim (that is W5-5-02's LLM-judge job).
- Whether URLs return 200 (network probe — out of scope for CI).

**What to build**:
Two artifacts:

1. **Fixture** `brief_50_claims.json`: a list of 50 dicts each shaped like:
   ```json
   {"claim": "AAPL beat revenue estimates by 5%", "context_articles": [{"id":"...","title":"...","summary":"...","url":"https://..."}], "context_events": [], "context_alerts": []}
   ```
   The fixture is **shape-realistic** (not content-realistic): URLs use `https://example.com/articles/<uuid>` so the parse test is deterministic. PLAN-0063 W5-5-02 will reuse the same fixture path for its LLM-judge cron — coordinate the fixture spec with that plan's W5-1 work before /implement of either side.

2. **Test** `test_brief_contract.py`:
   - **`test_response_validates_against_pydantic_schema`**: `PublicBriefingResponse.model_validate(...)` round-trips for all 50 entries.
   - **`test_every_bullet_has_at_least_one_citation`**: For each fixture entry, build a fake `BriefingContext`, call `_parse_sections_with_citations` + `_backfill_uncited_bullets` on a markdown body that the fixture supplies, assert every resulting bullet has `len(citations) >= 1`.
   - **`test_every_citation_url_is_well_formed`**: For each citation URL across all 50 fixtures, assert `urlparse(url).scheme in {"http","https"}` and `urlparse(url).netloc` non-empty. **No network calls.**
   - **`test_confidence_is_in_zero_to_one`**: For each fixture, the computed `confidence` is in `[0.0, 1.0]`.
   - **`test_stale_v1_shape_at_v2_cache_key_falls_through`** (I-6 follow-up): seed Valkey mock with a `v1`-shape JSON value at the new `v2` cache key (simulates rollback mid-flight); route handler must `cache_read_failed` warn-log and proceed to fresh generation rather than 500.

**Logic**:
- Fixture loading: `with open(Path(__file__).parent / "fixtures" / "brief_50_claims.json") as f: cases = json.load(f)`.
- Use `pytest.mark.parametrize` over the 50 cases for the per-fixture assertions.

**Tests to write** (this task IS the test task):
- 5 test functions; the parametrised ones run 50× each (≈200 executions). Counted as 5 test functions in the wave's "minimum new test count".

**Acceptance criteria**:
- [ ] Fixture committed and contains exactly 50 entries.
- [ ] All parametrised test cases pass.
- [ ] Test runs in <5s (no network).
- [ ] Docstring at top of `test_brief_contract.py` cross-links PLAN-0063 W5-5-02 as the runtime-accuracy owner.

#### Validation Gate (Wave C)
- [ ] `ruff` + `mypy` clean
- [ ] `pytest services/rag-chat -v` all pass; ≥12 new tests in this wave
- [ ] `pytest services/rag-chat/tests/contract/test_brief_contract.py -v` all pass
- [ ] `services/api-gateway` tests still pass (no behaviour change)

#### Break Impact
| Broken file | Why it breaks | Fix required |
|---|---|---|
| `services/rag-chat/tests/unit/api/test_public_briefings.py` | response shape changed (added `confidence`, `snippet` on citations) | update assertions to expect new fields |
| `services/api-gateway/tests/unit/test_proxy_briefings.py` (if exists) | proxy is byte-passthrough — should not break, but verify | run tests, no change expected |

#### Regression Guardrails
- **CLAUDE.md hard rule #11 (forward-compatible schemas)**: cache-key bump (`v1`→`v2`) is the formal mitigation for the bullets inner-type swap; old keys orphan-expire. Documented above and in §3 release-window note.
- **MEMORY: pre-commit ruff stash conflict** — if any of these files appears in `git diff` with both staged and working-tree copies, run `git diff --name-only | xargs git add` before commit.
- **MEMORY: FastAPI 204 status code** — not applicable (we return 200 with body).

---

### ✅ Wave D: Frontend types + shared `<StructuredBrief>` component (done 2026-05-03)

**Goal**: Update TypeScript types to mirror the new shape; build a single `<StructuredBrief>` component that renders the deterministic structure with click-through citations. No surface integration yet.
**Depends on**: Wave C complete (so the API contract is locked)
**Estimated effort**: 75 min
**Architecture layer**: UI

#### Pre-read
- `apps/worldview-web/types/api.ts` lines 1075–1130 (existing brief types)
- `apps/worldview-web/components/dashboard/MorningBriefCard.tsx` (skim — body rendering pattern)
- `apps/worldview-web/components/instrument/InstrumentBriefPanel.tsx` (skim)
- `docs/ui/DESIGN_SYSTEM.md` brief section (token classes for muted-foreground, citation chip styles)
- MEMORY: feedback_frontend_comments.md — heavy inline comments expected for new components

#### Tasks

##### T-W4-D-01: Update `BriefingResponse`, `BriefSection`, `BriefingCitation` TypeScript types
**Type**: schema
**depends_on**: T-W4-C-01
**blocks**: T-W4-D-02
**Target files**:
- `apps/worldview-web/types/api.ts` (modify lines 1075–1130)
**PRD reference**: §3 FR-T1-1

**What to build**:
- Add `BriefBullet`:
  ```ts
  export interface BriefBullet {
    text: string;
    citations: BriefCitation[];
  }
  ```
- Update `BriefSection.bullets` type to `BriefBullet[]` (was `string[]`).
- Add `BriefCitation` (mirroring backend `BriefCitation`):
  ```ts
  export interface BriefCitation {
    document_id: string;
    snippet: string;
    url: string | null;
    /** Back-compat: present in legacy responses but ignored by new components. */
    source_id?: string;
    source_type?: "article" | "event" | "alert";
    title?: string | null;
  }
  ```
- Update `BriefingResponse.citations` to `BriefCitation[]`.
- Add `confidence: number` to `BriefingResponse` (required from now on; the route layer always populates it).
- Add `lead: string | null` to `BriefingResponse` (revised 2026-05-03 — required key, may be null). The key MUST always be present in the response so TypeScript-strict consumers can rely on `brief.lead` being defined; null vs string distinguishes degraded-no-lead from non-degraded.
- Existing `BriefingCitation` interface: rename to `BriefCitation` and **re-export the old name as a type alias** for back-compat:
  ```ts
  /** @deprecated use BriefCitation. */
  export type BriefingCitation = BriefCitation;
  ```
- **Align TS `BriefingResponse.entity_mentions` with Pydantic** (audit 2026-05-03, I-3): the TS interface currently declares `entity_mentions: BriefingEntityMention[]` as **required** (verified `apps/worldview-web/types/api.ts:1111`), but `PublicBriefingResponse` (Pydantic, `services/rag-chat/src/rag_chat/api/schemas.py:152-178`) does NOT define this field. The pre-existing drift means any payload from S9 will lack `entity_mentions`, causing runtime undefined-access bugs in any code that does `brief.entity_mentions.map(...)`. **Decision (cheaper direction)**: mark TS `entity_mentions` optional (`entity_mentions?: BriefingEntityMention[]`) — do NOT add the field to Pydantic, since no backend produces it today. Audit any TS call site that touches `entity_mentions` and gate with `?? []`.

**Tests to write**:
- (TypeScript types — `pnpm typecheck` is the test.)
- 1 unit test in `apps/worldview-web/__tests__/types-brief.test.ts` (new) that constructs a sample `BriefingResponse` literal and asserts shape via `satisfies`.

**Acceptance criteria**:
- [ ] `pnpm typecheck` clean across `apps/worldview-web`.
- [ ] `pnpm lint` clean.
- [ ] No call site uses `bullets: string[]` anymore (will be enforced by type checker — failing call sites fixed in T-W4-E-*).
- [ ] `BriefingResponse.entity_mentions` is now optional (`entity_mentions?: BriefingEntityMention[]`); all consumer call sites guard with `?? []` (audit 2026-05-03 I-3 fix).

---

##### T-W4-D-02: Build `<StructuredBrief>` shared component
**Type**: impl
**depends_on**: T-W4-D-01
**blocks**: T-W4-D-03, T-W4-E-01
**Target files**:
- `apps/worldview-web/components/brief/StructuredBrief.tsx` (new)
- `apps/worldview-web/components/brief/index.ts` (new — barrel export)
**PRD reference**: §3 FR-T1-1

**What to build**:
A single React component that renders `{headline, lead, sections, confidence, generated_at}` deterministically. The `lead` is rendered as prose with inline numbered citation links `[1] [2]` (NOT chips); bullets render with end-of-line citation chips. Heavy inline comments per MEMORY (feedback_frontend_comments).

**Component spec** (revised 2026-05-03 — variants now mean what Sam needs per PRD-0034 §3 FR-T1-1):
```tsx
export interface StructuredBriefProps {
  /** The full briefing payload. Headline + lead + sections come from the structured fields;
   *  fallback to MarkdownContent over `narrative` only when BOTH `lead` is null AND `sections` is empty. */
  brief: BriefingResponse;
  /** Visual variant — controls which payload fields render and how:
   *  - "compact": headline + lead only. NO section cards. Used by dashboard collapsed,
   *    instrument subheader. Lead is the entire compact view (1 sentence to 1 paragraph).
   *  - "full":    headline + lead + sections. Used by dashboard expanded, instrument page.
   *  - "inline":  lead only (no headline, no sections). Used by chat brief-kind messages.
   *    Renders as a flowing prose paragraph with inline numbered citations — chat answers
   *    should look like prose, not dashboard widgets. */
  variant?: "compact" | "full" | "inline";
  /** When true, citation chips and inline lead-citation links are clickable; when false
   *  (loading/preview), they render as visually identical but non-clickable spans. */
  interactive?: boolean;
  /** Optional onCitationOpen — when provided, suppresses default new-tab nav so the
   *  caller can intercept (e.g. open a side-panel popover with the snippet). Receives
   *  the BriefCitation so the caller can render `citation.snippet` in their popover. */
  onCitationOpen?: (citation: BriefCitation) => void;
}
```

**Render logic** (revised 2026-05-03):
1. **Variant-driven layout**:
   - **`compact`**: render `<header>{brief.headline}</header>` + `<LeadProse lead={brief.lead} citations={brief.citations} interactive={interactive} onCitationOpen={onCitationOpen} />`. **No sections.** If `brief.lead` is null, fall back to a 1-line excerpt from `brief.narrative` (≤200 chars) plus a "limited synthesis" muted hint.
   - **`full`**: render headline + lead (as compact) + then iterate `brief.sections` as before with `<CitationChips>` per bullet. If `brief.lead` is null and `brief.sections` is empty, fall back to `<MarkdownContent>` over `brief.narrative` (only true degraded path).
   - **`inline`**: render only `<LeadProse>`. No headline (chat already has assistant-message chrome). No sections. Designed to look like a chat assistant prose reply with inline citations.
2. Confidence rendering (revised — promoted from "buried chip" to "trust signal"):
   - `confidence ≥ 0.8`: hidden.
   - `0.6 ≤ confidence < 0.8`: small `<span>` next to headline ("{N} sources") — informational, no colour.
   - `confidence < 0.6`: **amber banner above the brief body** ("Limited source coverage — verify before acting"). For a $19/mo paid analyst tool the trust signal must be at the top, not in a footer.
3. For each bullet: `<li>` with `bullet.text` followed by `<CitationChips citations={bullet.citations} interactive={interactive} onCitationOpen={...} />`.

**Sub-component `<LeadProse>`** (new — same file):
- Renders the `lead: string` with inline `[cN]` markers parsed at render time and replaced with numbered link-superscripts ("¹ ²"). The N maps directly into `brief.citations[N-1]`.
- Click on superscript: if `onCitationOpen` is set, calls it; else opens `citation.url` in a new tab via `<a target="_blank" rel="noopener">` (or non-clickable span if no url).
- **Snippet popover (NEW — revised 2026-05-03)**: callers may opt in by passing `onCitationOpen` to render the snippet in a side panel/popover instead of navigating away. The default behaviour stays new-tab so this is purely additive — but Sam's "verify-without-leaving" pattern (AlphaSense / Sentieo) is reachable via this hook. Recommended pattern (documented in component docstring): wrap consumers with a shadcn `<Sheet>` component that renders `citation.snippet` + a "Open source ↗" button.

**Sub-component `<CitationChips>`** (same file):
- Renders each citation as a 12px chip with the citation index ("[1]", "[2]"). On hover: tooltip shows `citation.title` + `citation.snippet`. On click (when `interactive && url`): if `onCitationOpen` is set, calls it; else opens `citation.url` in a new tab via `<a target="_blank" rel="noopener">`. When no url, renders as non-clickable span.

**Logic & Behavior**:
- Reuse existing tokens from DESIGN_SYSTEM.md — no new tokens.
- Citation chip style mirrors existing chat citation chip style (look in `components/chat/CitationList` or `apps/worldview-web/lib/api/chat.ts` for reference).
- **Numbering is GLOBAL across the brief** (revised 2026-05-03): the lead's `[cN]` superscripts and the bullets' `[N]` chips share the same N → `brief.citations[N-1]` mapping. This gives Sam a single citation namespace to reason about ("source 3 is referenced both in the lead and in bullet 2 of section 1") — was per-bullet which fragments the mental model. Citation numbering = position in `brief.citations[]` (1-indexed) which itself reflects the order context items were rendered to the LLM (per T-W4-B-01).
- **A11y**: `<li>` includes `aria-describedby` referencing a hidden `<dl>` of citation summaries; chips and lead superscripts have `aria-label="Source N: <title>"`.

**Tests to write** (new file `apps/worldview-web/__tests__/structured-brief.test.tsx`):
| Test name | What it verifies | Type |
|---|---|---|
| `renders headline + section titles in full variant` | exact text appears | unit |
| `renders one chip per citation` | bullet with 3 citations → 3 chips | unit |
| `chip carries href to citation.url when interactive` | anchor element with correct href | unit |
| `chip non-clickable when url is null` | renders span not anchor | unit |
| `falls back to MarkdownContent when lead is null AND sections is empty` | finds rendered markdown text | unit |
| `shows amber banner when confidence < 0.6` | banner with warn token visible | unit |
| `shows source-count badge when 0.6 ≤ confidence < 0.8` | inline span next to headline | unit |
| `hides confidence indicator when confidence ≥ 0.8` | no banner, no badge | unit |
| `calls onCitationOpen instead of default nav when handler provided` | spy invoked, no anchor click navigation | unit |
| `compact variant renders headline + lead, no section cards` | `screen.queryByRole("heading", {level: 3})` returns null | unit |
| `compact variant falls back to narrative excerpt when lead is null` | shows ≤200-char narrative excerpt + "limited synthesis" hint | unit |
| `inline variant renders lead only, no headline` | headline text NOT in DOM | unit |
| `lead inline citations render as superscripts` | `[c1]` text becomes `<sup>` with `aria-label="Source 1: ..."` | unit |
| `lead superscripts open citation url on click when interactive` | click on `<sup>` triggers anchor with correct href | unit |
| `global numbering across lead and bullets` | citation referenced in lead `[c2]` AND bullet `[c2]` resolves to the same `brief.citations[1]` | unit |
- Minimum new test count: 15 (was 9; +6 for variants, lead prose, confidence banner, global numbering)

**Downstream test impact**:
- None yet — component is new and not wired in (Wave E).

**Acceptance criteria**:
- [ ] Component file with heavy inline comments (per MEMORY).
- [ ] Barrel export `components/brief/index.ts`.
- [ ] 9+ unit tests passing.
- [ ] `pnpm typecheck`, `pnpm lint` clean.
- [ ] Visual: an in-source storybook-style comment block describes intended layout (no Storybook setup required).

---

##### T-W4-D-03: Citation deep-link helper + URL handling
**Type**: impl
**depends_on**: T-W4-D-02
**blocks**: T-W4-E-01
**Target files**:
- `apps/worldview-web/components/brief/citation-link.ts` (new helper)
**PRD reference**: §3 FR-T1-1 ("every bullet is click-through to source")

**What to build** (revised 2026-05-03 audit, I-4):
A pure helper `resolveCitationHref(c: BriefCitation): string | null` that:
1. Returns `c.url` if non-null.
2. Otherwise returns the deep-link path `/news/${c.document_id}` if `c.source_type === "article"`. (`apps/worldview-web/app/(app)/news/page.tsx` exists — but note: only the news LIST page exists today; `/news/:id` deep-link will only resolve once a `[id]/page.tsx` route is added. Until then, this fallback is best-effort; `<CitationChips>` MUST handle a 404-on-click gracefully.)
3. **Events / alerts fallbacks intentionally omitted**: `app/(app)/events/` does NOT exist (verified 2026-05-03), and `app/(app)/alerts/` exists only as a list page (no `[id]/page.tsx`). Returning a path for these source types would 404 and violate FR-T1-1 acceptance "every bullet is click-through to source." Therefore, for `source_type === "event"` or `"alert"` (and no external `url`), return `null` so `<CitationChips>` renders a non-clickable span. PRD acceptance is satisfied because the chip still surfaces title + snippet via tooltip. Adding dynamic routes for events/alerts is deferred to §15 follow-ups.
4. Returns null if no url and source_type is article-but-document_id-empty, or unknown.

Used by `<StructuredBrief>` `<CitationChips>` to give every citation a click target **when feasible**, and a hover-only chip otherwise.

**Tests to write**:
| Test name | What it verifies | Type |
|---|---|---|
| `external url passthrough` | url returned verbatim | unit |
| `article fallback to /news/:id` | document_id used in path | unit |
| `event source_type with no url returns null` | (revised) chip non-clickable; no `/events/:id` route exists yet | unit |
| `alert source_type with no url returns null` | (revised) chip non-clickable; no `/alerts/:id` route exists yet | unit |
| `null when no url and unknown source_type` | returns null | unit |
- Minimum new test count: 5

**Acceptance criteria**:
- [ ] Helper exported.
- [ ] `<StructuredBrief>` `<CitationChips>` uses it (refactor from D-02 if needed).

#### Validation Gate (Wave D)
- [ ] `pnpm typecheck` clean
- [ ] `pnpm lint` clean
- [ ] `pnpm test` — ≥15 new tests pass; existing tests still pass (the bullets-as-string-array tests will be in `__tests__/morning-brief-card.test.tsx` etc — those break in this wave because the type changed; **fix in E**, not here. **OR** stub the old type with `as any` casts in those tests temporarily, with a TODO comment pointing to the E task. Decision: stub with `as unknown as BriefSection[]` cast and TODO comment — keeps Wave D green without dragging in E rewrites.)
- [ ] `pnpm build` succeeds

#### Break Impact
| Broken file | Why it breaks | Fix required |
|---|---|---|
| `apps/worldview-web/__tests__/morning-brief-card.test.tsx` | `BriefSection.bullets` type changed to `BriefBullet[]` | Wave E rewrites this file fully; in Wave D apply temp `as unknown as` cast or `// @ts-expect-error: rewritten in W4-E-02` to keep Wave D green |
| `apps/worldview-web/__tests__/briefing.test.tsx` | same | same |
| `apps/worldview-web/__tests__/instrument-detail.test.tsx` | same | same |
| `apps/worldview-web/__tests__/dashboard.test.tsx` | same (if it touches brief) | same |
| `apps/worldview-web/__tests__/workspace.test.tsx` | `WorkspaceBriefWidget` type | same |
| `apps/worldview-web/components/dashboard/MorningBriefCard.tsx` | type-checks against new `BriefSection` shape | Wave E rewrites; in Wave D leave file untouched (it still type-checks because it consumes `narrative` not `sections`) |
| `apps/worldview-web/components/instrument/InstrumentBriefPanel.tsx`, `InstrumentAISubheader.tsx` | same | same |

#### Regression Guardrails
- **MEMORY: feedback_frontend_comments.md** — heavy inline comments are mandatory in `StructuredBrief.tsx`.
- **MEMORY: feedback_frontend_pnpm.md** — pnpm only, exact versions.
- **BP-300/F-STAB-002** (WebSocket isMountedRef) — not applicable.
- **W9 coordination**: do NOT alter the `--muted-foreground` token usage; reuse the existing class string verbatim.

---

### ✅ Wave E: Frontend integration (4 surfaces) + tests + parity audit (done 2026-05-03)

**Goal**: Replace the markdown-only render in `MorningBriefCard`, `InstrumentBriefPanel`, `InstrumentAISubheader`, any `WorkspaceBriefWidget` usage, **and chat assistant `MessageBubble` for brief-shaped payloads** with `<StructuredBrief>`. Update all impacted tests. Add a 4-surface parity test (dashboard + instrument panel + instrument subheader + chat).
**Depends on**: Wave D complete
**Estimated effort**: 90 min
**Architecture layer**: UI integration

#### Pre-read
- `apps/worldview-web/components/dashboard/MorningBriefCard.tsx` (full)
- `apps/worldview-web/components/instrument/InstrumentBriefPanel.tsx` (full)
- `apps/worldview-web/components/instrument/InstrumentAISubheader.tsx` (full)
- `apps/worldview-web/components/workspace/WorkspaceBriefWidget.tsx` (full — it consumes brief?)
- `apps/worldview-web/features/chat/components/MessageBubble.tsx` (full — verified path 2026-05-03; this is the chat assistant message renderer)
- All 5 tests files listed in §2 break-impact

#### Tasks

##### T-W4-E-01: Wire `<StructuredBrief>` into `MorningBriefCard`
**Type**: impl
**depends_on**: T-W4-D-02, T-W4-D-03
**blocks**: T-W4-E-04
**Target files**:
- `apps/worldview-web/components/dashboard/MorningBriefCard.tsx` (modify)
**PRD reference**: §3 FR-T1-1

**What to build**:
Replace the body region (currently `<MarkdownContent content={brief.narrative} />` plus the summary clamp) with `<StructuredBrief brief={brief} variant={isExpanded ? "full" : "compact"} interactive />`.

Preserve:
- Card chrome (header, expand toggle, refresh button, freshness dot).
- The "Top Stories" strip (separate from the brief body).
- The 503 soft-error path (replace markdown render with a friendly "generating..." message).

**Tests to write**:
- Update `apps/worldview-web/__tests__/morning-brief-card.test.tsx`:
  - Replace markdown-content assertions with structured-brief assertions ("section title visible", "bullet text appears", "citation chip renders for first bullet").
  - Keep all existing tests for chrome (expand toggle, error state, etc.).
- Add 2 new tests:
| Test name | What it verifies |
|---|---|
| `dashboard brief renders citation chip clickable` | first bullet's first citation chip is an `<a>` with non-empty href |
| `dashboard brief shows fallback markdown when sections empty` | with `sections:[]`, narrative markdown still renders |
- Total impacted: ~15 tests; ≥2 new.

**Acceptance criteria**:
- [ ] `MorningBriefCard.tsx` no longer imports `ReactMarkdown` for the body (only fallback path).
- [ ] All `__tests__/morning-brief-card.test.tsx` tests pass.

---

##### T-W4-E-02: Wire `<StructuredBrief>` into `InstrumentBriefPanel` + `InstrumentAISubheader`
**Type**: impl
**depends_on**: T-W4-D-02, T-W4-D-03
**blocks**: T-W4-E-04
**Target files**:
- `apps/worldview-web/components/instrument/InstrumentBriefPanel.tsx` (modify)
- `apps/worldview-web/components/instrument/InstrumentAISubheader.tsx` (modify)
**PRD reference**: §3 FR-T1-1 ("rendering is identical across dashboard, instrument page, and chat")

**What to build**:
Same swap as E-01: replace markdown body with `<StructuredBrief brief={brief} variant="full" interactive />` (instrument page is always expanded). The subheader uses `variant="compact"` (only headline + 1 section visible).

**Tests to write**:
- Update `apps/worldview-web/__tests__/instrument-detail.test.tsx`:
  - Replace markdown assertions with structured-brief assertions.
- Update `apps/worldview-web/__tests__/briefing.test.tsx`:
  - Same.
- Add 1 new test:
| Test name | What it verifies |
|---|---|
| `instrument brief renders citation chip clickable` | as in E-01 |

**Acceptance criteria**:
- [ ] Both components no longer render markdown for the body (fallback only).
- [ ] All impacted tests pass.

---

##### T-W4-E-03: Update `WorkspaceBriefWidget` (if it renders briefs) to use `<StructuredBrief>`
**Type**: impl
**depends_on**: T-W4-D-02
**blocks**: T-W4-E-04
**Target files**:
- `apps/worldview-web/components/workspace/WorkspaceBriefWidget.tsx` (modify if it renders briefs; otherwise verify and skip)
**PRD reference**: §3 FR-T1-1

**What to build**:
Inspect `WorkspaceBriefWidget.tsx`. If it renders a brief, swap to `<StructuredBrief>` (variant decided by widget size). If it does not (e.g. it's a different widget type), this task becomes "verify and skip" with a 1-line note in the wave summary.

**Tests to write**:
- Update `apps/worldview-web/__tests__/workspace.test.tsx` if needed.
- 0–2 new tests depending on what's there.

**Acceptance criteria**:
- [ ] Decision documented (swap performed OR no-op verified).
- [ ] All workspace tests pass.

---

##### T-W4-E-05: Wire `<StructuredBrief>` into chat assistant `MessageBubble`
**Type**: impl
**depends_on**: T-W4-D-02, T-W4-D-03
**blocks**: T-W4-E-04
**Target files**:
- `apps/worldview-web/features/chat/components/MessageBubble.tsx` (modify — verified path 2026-05-03)
**PRD reference**: §3 FR-T1-1 ("rendering is identical across dashboard, instrument page, and chat")

**Why this task exists** (audit 2026-05-03, B-2 resolution):
PRD acceptance demands 3-surface parity: dashboard + instrument + chat. The pre-revision plan silently descoped chat. The auditor verified `MessageBubble.tsx` does NOT currently render `BriefingResponse` payloads, so there is no inherited integration; this task creates one.

**What to build**:
1. Inspect the assistant-message render path in `MessageBubble.tsx`. Identify where the message content (markdown/text/tool-call output) is rendered.
2. Add a brief-payload detection branch: when the assistant message carries a `brief` field (or its content shape matches `BriefingResponse` — agree on a single discriminator with the chat backend; if no flag exists yet, gate this on a new `message.kind === "brief"` discriminator and have the chat assistant emit it when answering brief-class queries; the discriminator wire-up may be a small backend tweak coordinated with chat use cases).
3. When detected, render `<StructuredBrief brief={message.brief} variant="inline" interactive />` in place of the default markdown body.
4. Heavy inline comments per MEMORY (feedback_frontend_comments).
5. Preserve all non-brief message rendering paths unchanged.

**If the discriminator does not exist** (likely — verify in pre-read):
- Add a minimal type extension in `apps/worldview-web/types/api.ts` for the chat message shape: optional `brief?: BriefingResponse` and `kind?: "brief" | ...`.
- Document the contract in `docs/services/rag-chat.md` chat section.
- The actual server-side emission of `kind: "brief"` for brief-class chat answers may already exist (the chat use case sometimes returns structured payloads) — verify before code change. If absent, scope a 1-line follow-up (do NOT expand W4 to add a full chat-brief intent; that is a future workstream).

**Tests to write**:
| Test name | What it verifies | Type |
|---|---|---|
| `chat MessageBubble renders <StructuredBrief> for brief-kind message` | given a mock assistant message with `brief` payload, finds rendered headline + section title | unit |
| `chat MessageBubble renders default markdown for non-brief message` | regression: existing path unchanged | unit |
| `chat brief renders citation chip clickable` | first bullet's first citation chip is `<a>` with non-empty href | unit |
- Minimum new test count: 3.

**Acceptance criteria**:
- [ ] `MessageBubble.tsx` detects brief-shaped assistant messages and routes them through `<StructuredBrief variant="inline">`.
- [ ] Non-brief paths untouched (regression test passes).
- [ ] If the discriminator wire-up is incomplete server-side, a follow-up item is added to §15 with a clear scope.

---

##### T-W4-E-04: 4-surface parity test
**Type**: test
**depends_on**: T-W4-E-01, T-W4-E-02, T-W4-E-03, T-W4-E-05
**blocks**: none
**Target files**:
- `apps/worldview-web/__tests__/structured-brief-parity.test.tsx` (new)
**PRD reference**: §3 FR-T1-1 acceptance "rendering is identical across dashboard, instrument page, and chat"

**What to build** (revised 2026-05-03 — parity is now payload + citation-set, NOT layout):
A test that, given a single fixed `BriefingResponse` payload (with non-null `lead`, ≥2 sections, ≥4 citations), mounts each of {`MorningBriefCard`, `InstrumentBriefPanel`, `InstrumentAISubheader`, `MessageBubble` (chat, with brief-kind assistant message)} and asserts:
1. **Lead text parity (HIGH-VALUE)** — every `full`/`compact`/`inline` surface renders the exact lead string (modulo `[cN]` markers which become superscripts in the rendered DOM). Use `screen.getByText(brief.lead.replace(/\[c\d+(?:\s*,\s*c?\d+)*\]/g, "").trim())` per surface.
2. **Citation-href parity** — the union of hrefs in each surface (extracted via `screen.getAllByRole("link")` filtered by `aria-label^="Source"`) is a subset of `full` and a superset of `inline`/`compact`. The "subset" relationship is the relaxed parity from the revised PRD-0034 §3 FR-T1-1 acceptance "consistent" (was "identical"). For `full` surfaces (dashboard expanded, instrument page) the citation-href set MUST equal `brief.citations.map(c => c.url).filter(Boolean)`.
3. **Section-title set parity for full variants only** — `MorningBriefCard` (expanded) and `InstrumentBriefPanel` render the same set of section titles. `InstrumentAISubheader` (compact) and chat `MessageBubble` (inline) explicitly DO NOT render section titles — assert `screen.queryAllByRole("heading", { level: 3 })` is empty for those.
4. **Headline text parity** — `full` and `compact` surfaces render the headline; `inline` surface explicitly does NOT (assert headline text is NOT in DOM for chat).

This is the "consistent rendering" gate per the revised PRD acceptance — replaces the prior "identical rendering" gate which was infeasible given the deliberate variant differences.

**Logic**:
- Use a single `mockBrief` fixture imported in the test (with `lead`, `citations`, `sections`, `confidence: 0.85`).
- Use `render(...)` per surface, then `getAllByText` / `getAllByRole("link")` / etc to extract sets, assert per the parity rules above.

**Tests to write**:
- 1 test function with 4 sub-assertions (lead text, citation hrefs, section titles, headline). Each surface tested as a sub-test.
- Minimum new test count: 1 (high-value).

**Acceptance criteria**:
- [ ] All 4 surfaces share the same `lead` text content (modulo marker→superscript transformation).
- [ ] Citation hrefs in `compact`/`inline` are a subset of `full` (per documented variant policy).
- [ ] Section titles render only in `full` surfaces; `compact`/`inline` show none.
- [ ] No surface drops a citation from `brief.citations[]` that the user could otherwise click in `full` view.

#### Validation Gate (Wave E)
- [ ] `pnpm typecheck` clean
- [ ] `pnpm lint` clean
- [ ] `pnpm test` all pass
- [ ] No `// @ts-expect-error` markers from Wave D remain
- [ ] `pnpm build` succeeds
- [ ] Backend: `pytest services/rag-chat -v` still all pass
- [ ] Architecture tests: `pytest tests/architecture -v` still pass

#### Break Impact
| Broken file | Why it breaks | Fix required |
|---|---|---|
| `apps/worldview-web/__tests__/morning-brief-card.test.tsx` | new render shape | full rewrite per E-01 |
| `apps/worldview-web/__tests__/briefing.test.tsx` | same | rewrite per E-02 |
| `apps/worldview-web/__tests__/instrument-detail.test.tsx` | same | rewrite per E-02 |
| `apps/worldview-web/__tests__/dashboard.test.tsx` | indirect (snapshot of MorningBriefCard) | re-snapshot |
| `apps/worldview-web/__tests__/workspace.test.tsx` | possible | rewrite per E-03 |
| chat tests (e.g. `apps/worldview-web/__tests__/chat-message-bubble.test.tsx` or equivalent) | new brief-kind branch added in `MessageBubble` | add test cases per E-05 (do not delete existing tests — R19) |

#### Regression Guardrails
- **W9 coordination**: must not regress `--muted-foreground` contrast fix (FR-T2-3). Verify by visual snapshot.
- **MEMORY: never delete tests (R19)** — every test file above is _modified_, never deleted.
- **MEMORY: feedback_audit_returned_value_persistence.md** — `confidence` is computed by backend; surface it on at least one frontend test (E-01: low-confidence chip).
- **MEMORY: design feedback** — Bloomberg-grade density expected; reuse existing tokens; no new gradients/shadows.

---

## 7. Documentation Updates (Mandatory at Wave E completion)

| Doc | Update |
|---|---|
| `docs/services/rag-chat.md` | Add brief schema section: `BriefBullet`, `BriefCitation`, `confidence` field, cache-key v2 |
| `docs/services/api-gateway.md` | Note brief routes pass through new fields unchanged (T-W4-C-03) |
| `services/rag-chat/.claude-context.md` | Update API Endpoints table: `/api/v1/briefings/morning` and `/api/v1/briefings/instrument/{id}` now return `confidence` and structured `sections[].bullets[].citations` |
| `apps/worldview-web/components/brief/StructuredBrief.tsx` | Component-level docstring with reuse pattern |
| `docs/ui/DESIGN_SYSTEM.md` | (only if new tokens — none expected) |
| `docs/BUG_PATTERNS.md` | Compounding check — if any pattern emerges from implementation, add as BP |

---

## 8. Open Questions / Risks

| ID | Question | Severity | Default decision (this plan) | When to revisit |
|---|---|---|---|---|
| W4-OQ-1 | PRD-0034 §14 OQ-5 defers exact JSON Schema to PRD-0035 — should we wait? | MEDIUM | **No, proceed**: derive schema from FR-T1-1 verbatim. Surface to user. | Before Wave A start |
| W4-OQ-2 | Is `confidence` exposed to the user (chip on low values) or hidden (debug-only)? | RESOLVED (revised 2026-05-03) | **Tiered visibility**: `≥0.8` hidden; `0.6–0.8` inline source-count badge next to headline; `<0.6` amber banner above brief body ("Limited source coverage — verify before acting"). The trust signal is at the TOP for paid analysts, not buried in the footer. Implemented in T-W4-D-02 render logic. | n/a — closed |
| W4-OQ-3 | Should chat (PRD acceptance "identical across dashboard, instrument page, and chat") render full `<StructuredBrief>` or stay markdown? | RESOLVED (audit 2026-05-03) | **Resolved IN PLAN**: T-W4-E-05 wires `<StructuredBrief variant="inline">` into `apps/worldview-web/features/chat/components/MessageBubble.tsx` for brief-kind assistant messages. PRD acceptance closed at /qa via T-W4-E-04 4-surface parity test. | n/a — closed |
| W4-OQ-4 | The 50-claim fixture (C-04) — synthetic or real-source? | MEDIUM | **Synthetic with `https://example.com/...` URLs**: removes flakiness; live 404 probe gated by env var for nightly QA. | If user wants real-source, expand C-04 |
| W4-OQ-5 | Cache-key bump strategy: bump-and-orphan vs explicit clear? | LOW | **Bump-and-orphan**: 24h TTL handles cleanup. | If immediate consistency required |

---

## 9. Suggested Next Steps

1. **User reviews** open question §8 W4-OQ-1 (proceed without PRD-0035). W4-OQ-3 is closed by T-W4-E-05 (audit 2026-05-03 fix).
2. Invoke `/implement PLAN-0062 Wave A` to start.
3. After Wave E green, run `/qa` for a strict review against the schema/shape contract gate and the 4-surface parity test. Cross-check with PLAN-0063 W5-5-02 for runtime citation accuracy gating.

---

## 15. Follow-ups (deferred from audit 2026-05-03)

The following items were surfaced by the 2026-05-03 audit but are deferred from W4 scope. They MAY be picked up in W9 (visible regression cleanup) or as standalone follow-up tasks. Each is one-line tractable and has no blocking dependency on W4 closing.

| ID | Source | Description | Suggested owner |
|---|---|---|---|
| F-W4-1 | Audit N-3 | `coverage_factor = min(1.0, total_citations / 8.0)` divisor `8` is a value judgment; tune via telemetry once briefs are live. | W9 / observability follow-up |
| F-W4-2 | Audit N-4 | Fixture URLs use `https://example.com/articles/<uuid>` — shape-realistic, not content-realistic. If user wants real-source fixtures, expand via a snapshot of production briefs (privacy review needed). | W5 fixture co-design |
| F-W4-3 | Audit N-5 | Single PR diff size (~15-20 files). If reviewer fatigue becomes an issue, split after Wave C (backend) and after Wave E (frontend) into 2 sequential PRs — but the frontend PR MUST merge within the same deploy window per §3 release-window discipline. | release engineering |
| F-W4-4 | Audit I-4 | Add `app/(app)/news/[id]/page.tsx`, `app/(app)/events/[id]/page.tsx`, `app/(app)/alerts/[id]/page.tsx` dynamic routes so the citation deep-link helper can resolve all three source types. Until then, events/alerts citations are hover-only. | frontend follow-up |
| F-W4-5 | Audit B-2 + T-W4-E-05 | If chat backend does NOT yet emit `kind: "brief"` discriminator on assistant messages, wire a 1-line emission in the chat assistant use case so `MessageBubble` can route brief-shaped messages through `<StructuredBrief>`. Verify before Wave E starts; bump to a Wave E task if needed. | rag-chat follow-up |
| F-W4-6 | Audit Compounding Notes | Formalise cache-key versioning rule in `STANDARDS.md`: "When a non-additive shape change ships in a Valkey-cached response, the cache key prefix MUST be bumped (e.g., `:v1:` → `:v2:`) and the bump documented in the response model docstring." | docs-audit |
| F-W4-7 | Audit Compounding Notes | Improve `/plan` skill pre-flight gate to grep for the same PRD reference across all in-flight plans and surface every match (would have caught B-1 sooner). | skill maintenance |
