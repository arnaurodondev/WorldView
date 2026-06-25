# Prompts Library

> **Package**: `prompts` · **Path**: `libs/prompts/` · **Version**: 2025.6.0
> **Purpose**: Single source of truth for all LLM prompt templates across the
> platform. Prevents prompt drift, enables versioning, and ensures safety controls
> (XML-wrapping, `SAFETY_FOOTER`) are applied consistently.

---

## Purpose

Without a shared prompt library, each service would define its own inline prompt
strings — scattered across multiple files, impossible to audit, and prone to
divergence as the platform evolves. `prompts` centralises all templates so:

- **Prompt changes are tracked in version control** (template `version` fields
  make diffs readable).
- **Safety controls are consistently applied** — `SAFETY_FOOTER` is appended to all
  briefing and chat prompts; XML-wrapping prevents prompt injection in templates
  that accept user-controlled input.
- **Consumers always use the same template as the value advertised** — the "prompt
  input vs lookup mismatch" pattern (BP memory item) is impossible when both sides
  import the same `PromptTemplate` constant.
- **Parameter validation at render time** — missing required parameters raise
  `ValueError` immediately, not silently produce broken output.

`prompts` has **zero runtime dependencies** (pure stdlib Python). It is safe to
import in any context.

---

## Installation

```toml
[project]
dependencies = ["prompts"]
```

```bash
pip install -e "libs/prompts"
```

---

## Public API

### `PromptTemplate` (core type)

```python
from prompts import PromptTemplate

pt = PromptTemplate(
    name="example",
    version="1.0",
    description="An example prompt",
    template="Hello {name}, you are a {role}.",
    parameters=frozenset({"name", "role"}),
)

result = pt.render(name="Alice", role="analyst")
# → "Hello Alice, you are a analyst."
```

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Unique identifier (used for logging and debugging) |
| `version` | `str` | Semantic version string (e.g. `"1.0"`, `"2.1"`) |
| `description` | `str` | Human-readable description of the template's purpose |
| `template` | `str` | Python format string with `{parameter}` placeholders |
| `parameters` | `frozenset[str]` | Required parameter names — `render()` validates against this set |

**`render(**kwargs: str) → str`**
- Raises `ValueError` if any parameter in `self.parameters` is missing from `kwargs`.
- Extra `kwargs` beyond `self.parameters` are silently ignored.
- Substitution uses `str.format_map(kwargs)`.
- The template itself is frozen (immutable after creation).

**Construction-time validation (`__post_init__`)** — `PromptTemplate` is validated
the moment it is constructed (i.e. at import time), failing loud before any LLM call:
- **Semver guard** — `version` must match `MAJOR.MINOR` or `MAJOR.MINOR.PATCH`
  (regex `^\d+\.\d+(\.\d+)?$`). `"v1.2"`, pre-release, and build-metadata strings
  raise `ValueError`.
- **Brace guard (MN-5)** — the template body is parsed with `string.Formatter().parse`.
  Every `{slot}` must reference a declared `parameters` entry; literal braces (e.g. a
  JSON example `{{"score": 25}}`) must be doubled. An undeclared placeholder, a
  positional `{}`, or an unbalanced brace raises `ValueError` with a guidance message.

### Versioning & content hashing (PLAN-0107)

`PromptTemplate` now enforces a semver-shaped version and computes a content
hash of the template body at construction time. Both surface through a single
`identifier()` accessor used by judge artefacts, log lines, and evaluation
output filenames.

| Attribute / method | Description |
|--------------------|-------------|
| `version` (str) | Validated against `MAJOR.MINOR[.PATCH]` at construction — `"v1.2"` or non-semver strings raise `ValueError`. Bump MAJOR on incompatible rubric / prompt-shape changes, MINOR on additive changes, PATCH on wording-only fixes. |
| `content_hash` (str) | First 12 hex chars of `sha256(template.encode("utf-8"))`. Computed in `__post_init__` and frozen on the dataclass. Detects silent template-body edits that forget to bump `version` — two prompts that share a version but differ in body will have different hashes. |
| `identifier()` (method) | Returns `"<name>@<version>#<content_hash>"`, e.g. `"citation_judge@1.0#a1b2c3d4e5f6"`. This string is persisted on every judge call artefact (`q_<id>.json` carries `judge_prompt_id = template.identifier()`), so eval outputs are unambiguously linked to the exact rubric text that produced them. Also emitted in structlog as the `prompt_id` field on prompt-related events. |

**Why content hashes matter**: a prompt body edit that forgets to bump `version`
is otherwise invisible — eval artefacts produced before and after the edit
appear identical in metadata even though they were scored against different
rubrics. The 12-char sha256 prefix is short enough for log lines yet collision-
resistant for the realistic universe of prompt versions per service.

### `SAFETY_FOOTER` (constant)

```python
from prompts import SAFETY_FOOTER
```

A shared safety suffix appended to all briefing and chat prompts. Instructs the
LLM to ignore instructions embedded in retrieved content and avoid speculation.
Always pass it via the `safety` parameter rather than appending it manually.

---

## Prompt Catalogue

### Briefing Prompts (`prompts.briefing`)

```python
from prompts.briefing.morning import MORNING_BRIEFING
from prompts.briefing.instrument import INSTRUMENT_BRIEFING
```

| Template | Version | Parameters | Used by |
|----------|---------|------------|---------|
| `MORNING_BRIEFING` | 4.8 | `portfolio_context`, `news_context`, `alerts_context`, `market_overview`, `events_context`, `safety`, `current_date` | S8 `GenerateBriefingUseCase` |
| `INSTRUMENT_BRIEFING` | 4.3 | `entity_context`, `fundamentals_context`, `news_context`, `events_context`, `relationships_context`, `safety` | S8 `GenerateBriefingUseCase` |

### Chat Prompts (`prompts.chat`)

The `prompts.chat` package `__init__` re-exports the synthesis, tool-use, and
injection-classifier members. The 8 intent-specific system prompts live in
`prompts.chat.intent` and are normally consumed through the `get_system_prompt()`
helper rather than imported individually.

```python
from prompts.chat import (
    INJECTION_SAFETY_CLASSIFIER,
    SYNTHESIS_SYSTEM_PROMPT,
    TOOL_USE_SYSTEM_PROMPT_TEMPLATE,
    get_tool_use_system_prompt,
)
from prompts.chat.intent import get_system_prompt  # intent → rendered system prompt
```

| Template / function | Version | Parameters | Used by |
|---------------------|---------|------------|---------|
| `FACTUAL_LOOKUP`, `RELATIONSHIP`, `SIGNAL_INTEL`, `FINANCIAL_DATA`, `COMPARISON`, `REASONING`, `PORTFOLIO`, `GENERAL` (in `chat.intent`) | per-template | `safety` | S8 RAG-Chat — 8 intent-specific system prompts |
| `get_system_prompt(intent: str) -> str` (in `chat.intent`) | — | — | Looks up the template by intent name, renders it with `SAFETY_FOOTER`, falls back to `FACTUAL_LOOKUP` for unknown intents |
| `SYNTHESIS_SYSTEM_PROMPT` | 1.0 | `safety` | S8 final-answer synthesis (`chat_synthesis_system`) |
| `TOOL_USE_SYSTEM_PROMPT_TEMPLATE` | 1.9 | `today_iso`, `entity_map_section`, `per_intent_addendum` | S8 agentic tool-use system prompt |
| `get_tool_use_system_prompt(intent, today_iso, entity_map_section="")` | — | — | Renders `TOOL_USE_SYSTEM_PROMPT_TEMPLATE` with the per-intent addendum looked up from `intent` |
| `INJECTION_SAFETY_CLASSIFIER` | 4.0 | (none — pure system prompt) | S8 `LLMInjectionClassifier` — PLAN-0107 moved out of inline string in `llm_injection_classifier.py` |

### Classification Prompts (`prompts.classification`)

```python
from prompts.classification.intent import INTENT_CLASSIFICATION
from prompts.classification.article_relevance import ARTICLE_RELEVANCE_SCORER  # PLAN-0107
```

| Template | Parameters | Used by |
|----------|-----------|---------|
| `INTENT_CLASSIFICATION` (v2.1, PLAN-0107) | `message`, `history`, `entities` | S8 `IntentClassifier`. PLAN-0107 consolidated W49 + F-NEW-014 examples and priority rules into a single source of truth — previously the prompt existed both inline in `intent_classifier.py` and in libs/prompts and the two had diverged. |
| `ARTICLE_RELEVANCE_SCORER` (v1.0, PLAN-0107) | (none — pure system prompt) | S6 `ArticleRelevanceScoringWorker` |

### Evaluation Prompts (`prompts.evaluation`, PLAN-0107)

```python
from prompts.evaluation import CHAT_QUALITY_JUDGE, CITATION_JUDGE
# or directly:
from prompts.evaluation.chat_quality_judge import CHAT_QUALITY_JUDGE
from prompts.evaluation.citation_judge import CITATION_JUDGE
```

| Template | Version | Parameters | Used by |
|----------|---------|------------|---------|
| `CHAT_QUALITY_JUDGE` | 3.0 | (none — pure system prompt) | `scripts/chat_quality_judge.py` — 4-dim LLM-as-judge rubric over chat-eval transcripts |
| `CITATION_JUDGE` | 1.0 | `claim`, `snippet` | S8 `ScoreCitationAccuracyUseCase` (via `CitationJudgeAdapter`) — daily citation-accuracy cron (PLAN-0107) |

Both judge templates carry `version` + `content_hash` so the `judge_prompt_id =
template.identifier()` written to each evaluation artefact (`q_<id>.json`)
unambiguously links the scored output to the exact rubric text used.

### Extraction Prompts (`prompts.extraction`)

```python
from prompts.extraction.deep import DEEP_EXTRACTION
from prompts.extraction.entity_mention_classification import (
    ENTITY_MENTION_CLASSIFIER_SYSTEM,
    ENTITY_MENTION_CLASSIFIER_USER,
)  # PLAN-0107
```

| Template | Version | Parameters | Used by |
|----------|---------|------------|---------|
| `DEEP_EXTRACTION` | 1.7 | `entities`, `text` | S6 Block 10 `deep_extraction.py` |
| `ENTITY_MENTION_CLASSIFIER_SYSTEM` | 1.0 | (none — system turn) | S6 entity-mention classification — PLAN-0107 moved out of inline strings |
| `ENTITY_MENTION_CLASSIFIER_USER` | 1.0 | `surface`, `context` | S6 entity-mention classification — user turn |

### Knowledge Prompts (`prompts.knowledge`)

```python
from prompts.knowledge.summary import RELATION_SUMMARY
from prompts.knowledge.entity_profile import ENTITY_PROFILE
from prompts.knowledge.alias import ALIAS_GENERATION
from prompts.knowledge.entity_enrichment import SYSTEM_PROMPT, build_entity_enrichment_prompt
from prompts.knowledge.narrative_prose import NARRATIVE_PROSE  # PLAN-0107
```

| Template / function | Version | Parameters | Used by |
|---------------------|---------|------------|---------|
| `RELATION_SUMMARY` | 1.0 | `evidence_statements` | S7 Worker 13C `summary.py` |
| `ENTITY_PROFILE` | 2.2 | `name`, `entity_class` | S7 Worker 13E `provisional_enrichment.py` |
| `ALIAS_GENERATION` | 2.0 | `name`, `ticker`, `description`, `aliases_so_far` | S7 Consumer 13D-4 `instrument_consumer.py` |
| `SYSTEM_PROMPT` (plain `str` constant) | — | — | S7 Worker 13J enrichment — system turn only |
| `build_entity_enrichment_prompt(entity_name, entity_type, context_hint="")` | — | — | S7 Worker 13J — builds the user turn (injection-safe) |
| `NARRATIVE_PROSE` (PLAN-0107) | 1.0 | (none — pure system prompt) | S7 NarrativeGenerationWorker — moved out of inline string |

`knowledge.alias` also exports a `sanitize_description(raw: str | None) -> str` helper.

### Briefing Prompts — agentic scaffold (`prompts.briefing.agentic_plan`, PLAN-0107)

```python
from prompts.briefing.agentic_plan import AGENTIC_BRIEF_PLAN
```

| Template | Parameters | Used by |
|----------|-----------|---------|
| `AGENTIC_BRIEF_PLAN` (v0.1, scaffold) | (per template) | S8 `AgenticBriefGenerator` — EXPERIMENTAL, off by default (`RAG_CHAT_BRIEF_AGENTIC_ENABLED=false`) |

**`build_entity_enrichment_prompt` sanitizes `entity_name`** — strips ASCII control
characters and angle brackets via `sanitize_entity_name()` to prevent prompt
injection (PRD-0073 §12 F-SEC-02). The name is also capped at 200 characters.

### Description Prompts (`prompts.description`)

```python
from prompts.description.entity import ENTITY_DESCRIPTION
```

| Template | Version | Parameters | Used by |
|----------|---------|------------|---------|
| `ENTITY_DESCRIPTION` | 1.0 | `name`, `type`, `hints` | `ml_clients.GeminiDescriptionAdapter` |

The `name` parameter is wrapped in `<entity>...</entity>` XML delimiters in the
template, preventing a malicious canonical name from closing surrounding delimiters
or injecting instructions.

### Retrieval Prompts (`prompts.retrieval`)

```python
from prompts.retrieval.hyde import HYDE_EXPANSION
```

| Template | Version | Parameters | Used by |
|----------|---------|------------|---------|
| `HYDE_EXPANSION` | 2.0 | `query` | S8 `HydeRetriever` (Hypothetical Document Embedding) |

`HYDE_EXPANSION` explicitly instructs the model to avoid inventing specific
financial figures (prices, percentages, dates) to prevent embedding poisoning —
HyDE generates a passage to embed for retrieval, not for display to users.

---

## Package Structure

```
libs/prompts/src/prompts/
├── __init__.py              — Re-exports PromptTemplate, SAFETY_FOOTER, HYDE_EXPANSION
├── _base.py                 — PromptTemplate dataclass (semver-validated version,
│                              12-char sha256 content_hash, identifier())
├── _safety.py               — SAFETY_FOOTER constant
├── briefing/
│   ├── morning.py           — MORNING_BRIEFING
│   ├── instrument.py        — INSTRUMENT_BRIEFING
│   └── agentic_plan.py      — AGENTIC_BRIEF_PLAN (PLAN-0107, scaffold v0.1)
├── chat/
│   ├── __init__.py          — re-exports synthesis/tool-use/injection-classifier
│   ├── intent.py            — 8 intent-specific system prompts + get_system_prompt()
│   ├── safety.py            — re-exports SAFETY_FOOTER (convenience)
│   ├── safety_classifier.py — INJECTION_SAFETY_CLASSIFIER v4.0 (PLAN-0107)
│   ├── synthesis.py         — SYNTHESIS_SYSTEM_PROMPT v1.0
│   └── tool_use.py          — TOOL_USE_SYSTEM_PROMPT_TEMPLATE v1.9 + get_tool_use_system_prompt()
├── classification/
│   ├── intent.py            — INTENT_CLASSIFICATION v2.1 (PLAN-0107 consolidated)
│   └── article_relevance.py — ARTICLE_RELEVANCE_SCORER v1.0 (PLAN-0107)
├── description/
│   └── entity.py            — ENTITY_DESCRIPTION v1.0 (XML-wrapped)
├── evaluation/              — PLAN-0107 (LLM-as-judge rubrics)
│   ├── chat_quality_judge.py — CHAT_QUALITY_JUDGE v3.0
│   └── citation_judge.py    — CITATION_JUDGE v1.0
├── extraction/
│   ├── deep.py                              — DEEP_EXTRACTION v1.7
│   └── entity_mention_classification.py     — ENTITY_MENTION_CLASSIFIER_SYSTEM + _USER (PLAN-0107)
├── knowledge/
│   ├── alias.py             — ALIAS_GENERATION
│   ├── entity_enrichment.py — SYSTEM_PROMPT + build_entity_enrichment_prompt()
│   ├── entity_profile.py    — ENTITY_PROFILE
│   ├── narrative_prose.py   — NARRATIVE_PROSE (PLAN-0107)
│   └── summary.py           — RELATION_SUMMARY
└── retrieval/
    └── hyde.py              — HYDE_EXPANSION
```

---

## Usage Examples

```python
from prompts import PromptTemplate, SAFETY_FOOTER
from prompts.briefing.morning import MORNING_BRIEFING

# Render a briefing prompt:
text = MORNING_BRIEFING.render(
    portfolio_context="Portfolio has 5 positions, all tech...",
    news_context="Top stories: Apple earnings beat, Fed holds rates...",
    alerts_context="No active alerts.",
    market_overview="S&P 500 up 0.3%, VIX at 14.",
    events_context="Upcoming: NVDA earnings Thursday.",
    safety=SAFETY_FOOTER,
    current_date="2026-06-25",
)

# Render with missing required parameter — raises ValueError immediately:
# MORNING_BRIEFING.render(portfolio_context="...")  ← raises ValueError

# The entity enrichment prompt has a helper function for injection-safe build:
from prompts.knowledge.entity_enrichment import SYSTEM_PROMPT, build_entity_enrichment_prompt

user_msg = build_entity_enrichment_prompt(
    entity_name="Apple Inc.",
    entity_type="company",
    context_hint="ticker: AAPL, sector: Technology",
)
# Pass to LLM: messages=[{"role": "system", "content": SYSTEM_PROMPT},
#                         {"role": "user", "content": user_msg}]
```

---

## Architecture Notes

### Why frozen dataclasses for templates?

A `PromptTemplate` is a compile-time constant — it should never be mutated at
runtime. Frozen dataclasses prevent accidental mutation through aliasing (e.g.
`my_template.template = "..."` raises `FrozenInstanceError`). They also enable
safe sharing across concurrent requests without copying.

### Why `frozenset` for parameters?

A mutable `set` could be modified by a careless caller, causing subsequent
`render()` calls to accept or reject different parameters. `frozenset` is
immutable; the set of required parameters is fixed at construction time.

### Why `render()` raises on missing parameters?

Silent rendering with missing parameters produces subtly broken prompts (empty
substitutions that look valid but confuse the LLM). Failing loudly at `render()`
time surfaces the problem at the call site during development, not in production
when the LLM returns garbage.

### XML-wrapping for injection prevention

Templates that accept user-controlled values (entity names, query text) wrap those
values in XML delimiters (e.g. `<entity>{name}</entity>`) so the LLM treats the
contents as data rather than instructions. This is a defence-in-depth measure —
`sanitize_entity_name()` strips control chars first, then XML-wrapping provides a
second layer.

---

## Configuration

`prompts` has no configuration and reads no environment variables. All templates
are statically defined Python constants.

---

## Extension Points (Adding a New Prompt)

1. Create a module in the appropriate sub-package:
   `libs/prompts/src/prompts/<category>/<name>.py`
2. Define a `PromptTemplate` constant:
   ```python
   from prompts._base import PromptTemplate

   MY_TEMPLATE = PromptTemplate(
       name="my_template",
       version="1.0",
       description="Does X for Y use case.",
       template="Analyse {subject} in the context of {context}.",
       parameters=frozenset({"subject", "context"}),
   )
   ```
3. Add unit tests in `libs/prompts/tests/test_<category>_prompts.py` covering:
   - Successful render
   - Missing parameter raises `ValueError`
   - Extra kwargs are ignored
   - Version format is valid
4. Add `"prompts"` to the consuming service's `pyproject.toml` dependencies if
   not already present.
5. Replace the inline prompt string in the service with `MY_TEMPLATE.render(...)`.
6. Update this doc with the new template entry.

---

## Security

- **XML-wrapping** — `ENTITY_DESCRIPTION` and `build_entity_enrichment_prompt()`
  wrap user-controlled values in XML delimiters. Never remove these.
- **`SAFETY_FOOTER`** — always pass via the `safety` parameter in briefing and chat
  prompts; never omit it.
- **Input truncation** — the library does not enforce input length limits. Callers
  are responsible for truncating inputs before `render()`. The
  `build_entity_enrichment_prompt()` helper caps `entity_name` at 200 characters
  but does not truncate `context_hint`.

---

## Testing

```bash
cd libs/prompts
python -m pytest tests/ -v
```

182 tests cover all templates: render validation, parameter checking, semver +
brace-guard construction validation, content-hash/identifier behaviour, frozen
immutability, and injection-safety helpers.
