# Tools Library

> **Package**: `tools` · **Path**: `libs/tools/` · **Version**: 0.1.0
> **Purpose**: Shared LLM tool-use registry and type layer for the RAG/Chat service
> (S8). Provides the tool manifest, capability registry, OpenAI-compatible function
> definitions, and canonical response types that drive the tool-use loop.

---

## Purpose

The `tools` library solves the problem of keeping tool definitions consistent across
three consumers that must all agree on the same schema:

1. **The LLM prompt** — the manifest section injected into system prompts so the LLM
   knows which tools it can call.
2. **The orchestrator** — the chat pipeline that parses LLM tool-call responses and
   dispatches to the correct handler.
3. **Architecture tests** — tests that verify the capability manifest YAML stays in
   sync with registered tools (rule R29).

Without a shared library, these three places would drift independently. `tools`
provides:

- **`ToolSpec` / `ParameterSpec`** — frozen dataclasses that describe each tool's
  name, description, and parameter schema in a single place.
- **`ToolRegistry`** — central lookup that maps tool names to specs and handler
  callables; renders OpenAI-compatible function definitions and system-prompt
  manifest sections from the same spec set.
- **`capability_manifest.yaml`** — the canonical YAML reference for all 22 platform
  tools, versioned alongside the code.
- **`LLMToolResponse` / `ToolCallBatch` / `ToolUseBlock`** — typed response objects
  shared between the LLM provider port and every concrete adapter
  (DeepInfra, OpenRouter, Ollama) so adapter code never imports from sibling adapters.

The library has a single dependency: `pyyaml` (for manifest loading). It has no
knowledge of HTTP, databases, Kafka, or any external service — it is a pure
definition/type layer.

---

## Installation

Add to a service's `pyproject.toml`:

```toml
[project]
dependencies = ["tools"]
```

Install in development (editable):

```bash
pip install -e "libs/tools"
pip install -e "libs/tools[dev]"  # includes pytest, ruff, mypy
```

Because the library has no `py.typed` marker, mypy requires suppression annotations
at import sites:

```python
from tools.tool_registry import ToolRegistry  # type: ignore[import-untyped,import-not-found]
from tools.tool_spec import ParameterSpec, ToolSpec  # type: ignore[import-untyped,import-not-found]
from tools.types import LLMToolResponse  # type: ignore[import-untyped]
```

Python 3.11–3.12.

---

## Public API

### `ParameterSpec`

```python
@dataclass(frozen=True, kw_only=True)
class ParameterSpec:
    name: str
    type: str         # "string" | "date" | "integer" | "number" | "boolean" | "array" | "object"
    description: str
    required: bool = True
    enum: list[str] | None = None
```

Describes a single parameter in a tool's input signature. `type` values map to
JSON Schema types; `"date"` maps to `{"type": "string", "format": "date"}` when
converted to OpenAI function definitions. `enum` constrains the LLM to a known
allowlist (e.g. severity tiers, bar intervals).

---

### `ToolSpec`

```python
@dataclass(frozen=True, kw_only=True)
class ToolSpec:
    name: str
    description: str
    parameters: list[ParameterSpec]
    source_type: str         # used by TrustScorer for authority weight (R29)
    example_queries: list[str] = field(default_factory=list)
```

Full specification for a single LLM-callable tool. `source_type` encodes where
results come from (`"ohlcv"`, `"fundamentals"`, `"knowledge_graph"`, `"portfolio"`,
`"narrative"`, `"market_data"`, `"alert"`, `"mixed"`) — used by `TrustScorer` to
compute authority weight at query time. Per rule R29, trust weight is **not** stored
here; `TrustScorer` computes it dynamically.

---

### `ToolRegistry`

```python
class ToolRegistry:
    def register(self, spec: ToolSpec, handler: Callable[..., Any]) -> None: ...
    def get_spec(self, name: str) -> ToolSpec | None: ...
    def get_handler(self, name: str) -> Callable[..., Any] | None: ...
    def all_specs(self) -> list[ToolSpec]: ...
    def to_system_prompt_section(self) -> str: ...
    def to_tool_definitions(self) -> list[dict[str, Any]]: ...
    def load_manifest(self) -> dict[str, Any]: ...
```

Central lookup for all registered tools. Thread-safe after construction (no mutation
after startup).

| Method | Returns | Description |
|--------|---------|-------------|
| `register(spec, handler)` | `None` | Register a tool spec and its async handler callable. The handler accepts tool input kwargs and returns a result (typically `RetrievedItem \| None`). |
| `get_spec(name)` | `ToolSpec \| None` | Return the spec for a registered tool; `None` if unknown (no `KeyError`). |
| `get_handler(name)` | `Callable \| None` | Return the handler for a registered tool; `None` if unknown. |
| `all_specs()` | `list[ToolSpec]` | All registered specs in registration order. |
| `to_system_prompt_section()` | `str` | Fenced `\`\`\`yaml` block for injection into LLM system prompts. Truncates descriptions to 200 chars. |
| `to_tool_definitions()` | `list[dict]` | OpenAI `chat.completions` `tools` format — pass directly to `AsyncOpenAI` or any OpenAI-compatible endpoint. |
| `load_manifest()` | `dict` | Parsed `capability_manifest.yaml` for architecture sync tests. |

**`to_tool_definitions()` type mapping:**

| `ParameterSpec.type` | JSON Schema |
|----------------------|-------------|
| `string` | `{"type": "string"}` |
| `date` | `{"type": "string", "format": "date"}` |
| `integer` | `{"type": "integer"}` |
| `number` | `{"type": "number"}` |
| `boolean` | `{"type": "boolean"}` |
| `array` | `{"type": "array", "items": {"type": "string"}}` |
| `object` | `{"type": "object"}` |

---

### `ToolUseBlock`

```python
@dataclass
class ToolUseBlock:
    id: str    # LLM-assigned call ID, e.g. "call_abc123" (OpenAI-compat field name)
    name: str  # tool name — must match a key in the ToolRegistry
    input: dict  # parsed JSON arguments from the LLM
```

Represents a single tool call emitted by the LLM. Uses `id` (not `tool_use_id`)
to match the OpenAI/DeepInfra/OpenRouter wire format directly.

---

### `ToolCallBatch`

```python
@dataclass
class ToolCallBatch:
    tool_calls: list[ToolUseBlock] = field(default_factory=list)
    finish_reason: str = "tool_calls"

    @property
    def has_tool_calls(self) -> bool: ...
```

Yielded from the LLM stream when `finish_reason == "tool_calls"`. Provides a clean
typed signal to the orchestrator to stop accumulating text and start dispatching.

---

### `LLMToolResponse`

```python
@dataclass
class LLMToolResponse:
    text: str | None               # set when finish_reason == "stop"
    tool_calls: list[ToolUseBlock] # non-empty when finish_reason == "tool_calls"
    finish_reason: str             # "stop" | "tool_calls" | "length"
    usage: dict | None = None      # {"prompt_tokens": N, "completion_tokens": M, ...}

    @property
    def has_tool_calls(self) -> bool: ...
```

Non-streaming response from `chat_with_tools()`. Exactly one of `text` or
`tool_calls` is populated depending on `finish_reason`. `usage` carries token counts
from the response body so callers can log cost without an extra round-trip.

---

### `capability_manifest.yaml`

Canonical YAML file at `libs/tools/src/tools/capability_manifest.yaml`. Contains
all 22 registered tools, organized into four version groups:

| Version | Tools | Source types |
|---------|-------|--------------|
| v1 (PLAN-0066) | `get_price_history`, `get_fundamentals_history`, `search_documents`, `get_entity_graph`, `traverse_graph`, `search_entity_relations`, `search_claims`, `search_events`, `get_contradictions`, `get_portfolio_context` | ohlcv, fundamentals, mixed, knowledge_graph, portfolio |
| v2 (PLAN-0080) | `get_entity_narrative`, `get_entity_paths`, `get_entity_health`, `get_entity_intelligence` | narrative, knowledge_graph |
| v3 (PLAN-0081) | `get_morning_brief`, `compare_entities`, `screen_universe`, `get_market_movers`, `get_economic_calendar`, `get_earnings_calendar` | narrative, fundamentals, market_data |
| v4 (PLAN-0082) | `get_alerts`, `create_alert` | alert |

Each YAML entry has: `name`, `description`, `parameters[]`, `source_type`, `since`,
`deprecated_at`, and `example_queries[]`. The `create_alert` entry additionally
carries `requires_confirmation: true`.

Rule R29: every registered tool must have a corresponding entry in this file.
Architecture tests in `test_tool_registry.py` enforce this invariant automatically.

---

## Usage Examples

### 1. Building a registry at service startup

```python
from tools import ParameterSpec, ToolRegistry, ToolSpec

def build_registry() -> ToolRegistry:
    registry = ToolRegistry()

    registry.register(
        ToolSpec(
            name="get_price_history",
            description="Fetches OHLCV history for a stock ticker.",
            parameters=[
                ParameterSpec(name="ticker", type="string",
                              description="Stock ticker symbol", required=True),
                ParameterSpec(name="from_date", type="date",
                              description="Start date (YYYY-MM-DD)", required=True),
                ParameterSpec(name="to_date", type="date",
                              description="End date (YYYY-MM-DD)", required=True),
                ParameterSpec(name="interval", type="string",
                              description="Bar granularity: day/week/month",
                              required=False, enum=["day", "week", "month"]),
            ],
            source_type="ohlcv",
        ),
        handler=my_price_history_handler,  # async callable
    )

    return registry
```

### 2. Injecting the manifest into an LLM system prompt

```python
registry = build_registry()

system_prompt = f"""You are a financial analyst assistant.
{registry.to_system_prompt_section()}
When you need data, emit a tool_use JSON block.
"""
```

The `to_system_prompt_section()` output is a fenced `\`\`\`yaml` block listing
all registered tools with their names, descriptions, and parameter schemas. It is
inserted into the system prompt so the LLM knows how to invoke tools.

### 3. Passing OpenAI-compatible tool definitions to an LLM adapter

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(base_url="https://api.deepinfra.com/v1/openai", api_key=api_key)
registry = build_registry()
tool_defs = registry.to_tool_definitions()  # list of OpenAI function-calling dicts

response = await client.chat.completions.create(
    model="meta-llama/Meta-Llama-3.1-8B-Instruct",
    messages=messages,
    tools=tool_defs,
    tool_choice="auto",
)
```

### 4. Parsing LLM tool-call responses

```python
from tools import LLMToolResponse, ToolCallBatch, ToolUseBlock

# After receiving an LLM response with finish_reason == "tool_calls":
response: LLMToolResponse = await llm_provider.chat_with_tools(messages, tool_defs)

if response.has_tool_calls:
    for call in response.tool_calls:
        handler = registry.get_handler(call.name)
        if handler is not None:
            result = await handler(**call.input)
        # append result to messages and continue the loop
else:
    final_answer = response.text
```

### 5. Architecture sync test pattern (R29)

```python
from tools import ToolRegistry

def test_all_registered_tools_in_manifest() -> None:
    registry = build_default_registry()
    manifest = registry.load_manifest()

    manifest_names = {t["name"] for t in manifest["tools"]}
    registered_names = {s.name for s in registry.all_specs()}

    missing = registered_names - manifest_names
    assert not missing, (
        f"Tools missing from capability_manifest.yaml: {missing}. "
        "Update libs/tools/src/tools/capability_manifest.yaml."
    )
```

---

## Architecture Notes

### Why a shared library instead of inline definitions in rag-chat?

Three consumers must agree on the exact same tool schema:

1. The LLM needs the manifest in the system prompt to know which tools exist.
2. The orchestrator needs the same schema to call `to_tool_definitions()` and pass
   it to the OpenAI client.
3. Architecture tests need `load_manifest()` to enforce R29 sync invariants.

If definitions lived inside rag-chat, sharing with tests and other future services
would require either duplication or circular imports.

### `to_system_prompt_section()` vs `to_tool_definitions()`

These serve different LLM interaction modes:

- `to_system_prompt_section()` produces a human-readable YAML block for
  instruction-following models that parse tool calls from free-form text.
- `to_tool_definitions()` produces the structured JSON required by OpenAI's native
  function-calling API. This is the production path — native function calling is
  more reliable because the model's sampling is constrained to produce valid JSON.

The orchestrator checks `hasattr(registry, "to_tool_definitions")` before deciding
which path to use. Both methods exist on `ToolRegistry`.

### Trust weight is NOT stored in `ToolSpec`

Per rule R29, `ToolSpec.source_type` is a metadata hint for `TrustScorer`. Trust
weight is computed dynamically at query time from `SOURCE_AUTHORITY * recency_decay
* corroboration * extraction_confidence`. Storing a static weight in `ToolSpec`
would produce stale values as the platform's knowledge base grows.

### Handler stubs in the production registry

The rag-chat service's `build_default_registry()` registers all 22 tools with
`handler=lambda **_: None` stubs. Actual dispatch happens inside
`ToolExecutor.execute()` via name-based routing, not through the registry handler.
The handler field is kept for future extension when the tool catalog grows to
support arbitrary callable dispatch.

### `ToolUseBlock.id` vs `tool_use_id`

The field is named `id` (not `tool_use_id`) to match the OpenAI/DeepInfra/OpenRouter
wire format exactly (`{"id": "call_abc123", "function": {...}}`). Anthropic's native
API uses `tool_use_id`; that field name is used in the older in-service executor.
The naming divergence is documented in `types.py` and will be harmonised in a
future wave.

---

## Configuration

The `tools` library reads no environment variables. All configuration (tool
descriptions, parameter schemas, example queries) is baked into `ToolSpec`
constructors or loaded from `capability_manifest.yaml`.

---

## Extension Points

### Adding a new tool

1. Add a new entry to `libs/tools/src/tools/capability_manifest.yaml` with:
   `name`, `description`, `parameters[]`, `source_type`, `since`, `deprecated_at`,
   and `example_queries[]`.
2. Register a `ToolSpec` in the service's `build_default_registry()` function,
   mirroring the YAML entry exactly (R29: the architecture sync test will fail
   otherwise).
3. Add a handler case in `ToolExecutor.execute()` in rag-chat.
4. If the new tool requires a new `source_type`, document it in this file and
   register its authority weight in `TrustScorer`.

### Adding a new parameter type

Extend the `to_tool_definitions()` type-mapping block in `tool_registry.py`:

```python
elif p.type == "my_new_type":
    schema["type"] = "string"        # or whatever JSON Schema type maps to it
    schema["format"] = "my-format"   # optional JSON Schema format hint
```

Also add test coverage in `TestToolDefinitions` (see `tests/test_tool_registry.py`).

---

## Testing

```bash
cd libs/tools

# Run all unit tests:
python -m pytest tests/ -v --tb=short

# Run with markers:
python -m pytest tests/ -m unit -v

# Type checking and lint:
mypy --strict src/
ruff check src/ tests/
```

The test suite covers:

- `TestToolRegistryGetSpec` — register/retrieve round-trips, unknown-key safety.
- `TestSystemPromptSection` — fenced YAML output, description truncation.
- `TestToolDefinitions` — OpenAI envelope shape, `date` format mapping, `array`
  items schema, enum propagation, zero-parameter tools, all primitive type mappings.
- `TestManifestArchitecture` — R29 sync assertion (every registered tool in YAML),
  YAML validity (version + tools fields), required YAML fields per entry.

No external services or network calls are required.
