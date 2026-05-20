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

**`render(**kwargs) → str`**
- Raises `ValueError` if any parameter in `self.parameters` is missing from `kwargs`.
- Extra `kwargs` beyond `self.parameters` are silently ignored.
- The template itself is frozen (immutable after creation).

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

| Template | Parameters | Used by |
|----------|-----------|---------|
| `MORNING_BRIEFING` | `portfolio_context`, `news_context`, `alerts_context`, `market_overview`, `events_context`, `safety` | S8 `GenerateBriefingUseCase` |
| `INSTRUMENT_BRIEFING` | `entity_context`, `fundamentals_context`, `news_context`, `events_context`, `relationships_context`, `safety` | S8 `GenerateBriefingUseCase` |

### Chat Prompts (`prompts.chat`)

```python
from prompts.chat.intent import INTENT_SYSTEM_PORTFOLIO, INTENT_SYSTEM_MARKET, ...
from prompts.chat.safety import CHAT_SAFETY
```

| Template | Parameters | Used by |
|----------|-----------|---------|
| `INTENT_SYSTEM_*` (8 intent-specific templates) | Varies per intent | S8 `PromptBuilder` |
| `CHAT_SAFETY` | — | S8 `PromptBuilder` |

### Classification Prompts (`prompts.classification`)

```python
from prompts.classification.intent import INTENT_CLASSIFICATION
```

| Template | Parameters | Used by |
|----------|-----------|---------|
| `INTENT_CLASSIFICATION` | `intents`, `question` | S8 `OllamaIntentClassifier` |

### Extraction Prompts (`prompts.extraction`)

```python
from prompts.extraction.deep import DEEP_EXTRACTION
```

| Template | Parameters | Used by |
|----------|-----------|---------|
| `DEEP_EXTRACTION` | `entities`, `text` | S6 Block 10 `deep_extraction.py` |

### Knowledge Prompts (`prompts.knowledge`)

```python
from prompts.knowledge.summary import RELATION_SUMMARY
from prompts.knowledge.entity_profile import ENTITY_PROFILE
from prompts.knowledge.alias import ALIAS_GENERATION
from prompts.knowledge.entity_enrichment import SYSTEM_PROMPT, build_entity_enrichment_prompt
```

| Template / function | Parameters | Used by |
|---------------------|-----------|---------|
| `RELATION_SUMMARY` | `evidence_statements` | S7 Worker 13C `summary.py` |
| `ENTITY_PROFILE` | `name`, `entity_class` | S7 Worker 13E `provisional_enrichment.py` |
| `ALIAS_GENERATION` | `name`, `ticker` | S7 Consumer 13D-4 `instrument_consumer.py` |
| `SYSTEM_PROMPT` (module-level constant) | — | S7 Worker 13J enrichment — system turn only |
| `build_entity_enrichment_prompt(entity_name, entity_type, context_hint)` | — | S7 Worker 13J — builds user turn |

**`build_entity_enrichment_prompt` sanitizes `entity_name`** — strips ASCII control
characters and angle brackets via `sanitize_entity_name()` to prevent prompt
injection (PRD-0073 §12 F-SEC-02). The name is also capped at 200 characters.

### Description Prompts (`prompts.description`)

```python
from prompts.description.entity import ENTITY_DESCRIPTION
```

| Template | Parameters | Used by |
|----------|-----------|---------|
| `ENTITY_DESCRIPTION` | `name`, `type`, `hints` | `ml_clients.GeminiDescriptionAdapter` |

The `name` parameter is wrapped in `<entity>...</entity>` XML delimiters in the
template, preventing a malicious canonical name from closing surrounding delimiters
or injecting instructions.

### Retrieval Prompts (`prompts.retrieval`)

```python
from prompts.retrieval.hyde import HYDE_EXPANSION
```

| Template | Parameters | Used by |
|----------|-----------|---------|
| `HYDE_EXPANSION` | `query` | S8 `HydeRetriever` (Hypothetical Document Embedding) |

`HYDE_EXPANSION` explicitly instructs the model to avoid inventing specific
financial figures (prices, percentages, dates) to prevent embedding poisoning —
HyDE generates a passage to embed for retrieval, not for display to users.

---

## Package Structure

```
libs/prompts/src/prompts/
├── __init__.py              — Re-exports PromptTemplate, SAFETY_FOOTER
├── _base.py                 — PromptTemplate dataclass
├── _safety.py               — SAFETY_FOOTER constant
├── briefing/
│   ├── morning.py           — MORNING_BRIEFING
│   └── instrument.py        — INSTRUMENT_BRIEFING
├── chat/
│   ├── intent.py            — 8 intent-specific system prompts
│   └── safety.py            — CHAT_SAFETY
├── classification/
│   └── intent.py            — INTENT_CLASSIFICATION
├── description/
│   └── entity.py            — ENTITY_DESCRIPTION (XML-wrapped)
├── extraction/
│   └── deep.py              — DEEP_EXTRACTION
├── knowledge/
│   ├── alias.py             — ALIAS_GENERATION
│   ├── entity_enrichment.py — SYSTEM_PROMPT + build_entity_enrichment_prompt()
│   ├── entity_profile.py    — ENTITY_PROFILE
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

52 tests cover all templates: render validation, parameter checking, version format,
frozen immutability, and injection-safety helpers.
