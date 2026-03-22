# Execution Prompt 0011 — Ingestion Pipeline v1 Foundations · Wave 02

## Context (read first)

- **Planning response**: `docs/ai-interactions/agent-responses/0011-response-20260322-ingestion-pipeline-v1-foundations.md`
- **Authoritative spec**: `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md` §4.3, §5 Blocks 4/7/10

## Assigned agent profile(s)

- `.claude/agents/machine-learning-lead.md`

## Mandatory pre-read

1. `AGENTS.md`
2. `CLAUDE.md`
3. `RULES.md`
4. `docs/ai-interactions/agent-responses/0011-response-20260322-ingestion-pipeline-v1-foundations.md` — task specs for T-F-004, T-F-005, T-F-006
5. `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md` §4.3 (S6 ENV vars), §5 Blocks 4, 7, 10 (adapter use contexts)
6. `.claude/agents/machine-learning-lead.md` (protocol and adapter specs)
7. `libs/common/pyproject.toml` (Hatch scaffold reference)
8. `libs/messaging/src/messaging/kafka/consumer/errors.py` (RetryableError, FatalError)
9. `libs/messaging/pyproject.toml` (dependency version reference)
10. `docs/libs/messaging.md` (lib doc style reference)

## Objective

Create `libs/ml-clients` as the sixth shared library. This library is the ONLY path through which S6 and S7 call ML models. It must be fully functional — protocols, dataclasses, four concrete adapters, unit tests, and documentation — before S6/S7 service implementation begins in Prompt 0017.

**No service logic here.** This wave only creates the shared library and its documentation.

## Task scope for this wave

### Sequential group (T-F-004 → T-F-005 → T-F-006)

| Task | What | Blocks |
|------|------|--------|
| **T-F-004** | Library scaffold: pyproject.toml, protocols, dataclasses, config | T-F-005 |
| **T-F-005** | Four concrete adapters + error wrapping + semaphore injection | T-F-006 |
| **T-F-006** | Unit tests + integration test stubs + docs/libs/ml-clients.md | — |

## Why this chunk

`libs/ml-clients` is a dependency of both S6 NLP Pipeline and S7 Knowledge Graph. Neither service can be built (Prompt 0017) until the protocol interfaces and adapters exist. This wave is isolated to the `libs/ml-clients/` directory — no service code is touched.

## Implementation instructions

### T-F-004 — Library scaffold (protocols + dataclasses + config)

**1. Create directory structure**:
```
libs/ml-clients/
├── pyproject.toml
├── src/
│   └── ml_clients/
│       ├── __init__.py
│       ├── protocols.py
│       ├── dataclasses.py
│       ├── errors.py
│       ├── config.py
│       └── adapters/
│           └── __init__.py
└── tests/
    ├── __init__.py
    ├── conftest.py
    └── test_protocols.py
```

**2. `pyproject.toml`** — follow `libs/common/pyproject.toml` pattern:
- `name = "ml-clients"`, `version = "0.1.0"`, `requires-python = ">=3.12"`
- Dependencies: `pydantic-settings>=2.0`, `structlog>=24.0`, `httpx>=0.27` (for Ollama HTTP calls)
- Optional: `gliner = {version = ">=0.2", optional = true}`, `anthropic = {version = ">=0.30", optional = true}`
- Extras: `[tool.hatch.envs.default.dependencies]` — dev deps: `pytest>=8`, `pytest-asyncio>=0.23`
- Add `messaging` as a workspace dependency (same pattern as other libs depending on `common`)
- Ruff + mypy configuration: inherit from root `ruff.toml` and `mypy.ini`

**3. `src/ml_clients/protocols.py`** — three Protocols, structural typing ONLY:
```python
from __future__ import annotations
from typing import Protocol, runtime_checkable
from ml_clients.dataclasses import (
    EmbeddingInput, EmbeddingOutput, NERInput, NEROutput, ExtractionInput, ExtractionOutput
)

@runtime_checkable
class EmbeddingClient(Protocol):
    """Embed a batch of texts into dense vectors."""
    async def embed(self, inputs: list[EmbeddingInput]) -> list[EmbeddingOutput]: ...

@runtime_checkable
class NERClient(Protocol):
    """Extract named entity mentions from text."""
    async def extract_entities(self, inp: NERInput) -> NEROutput: ...

@runtime_checkable
class ExtractionClient(Protocol):
    """Run structured LLM extraction against a schema."""
    async def extract(self, inp: ExtractionInput) -> ExtractionOutput: ...
```
CRITICAL: `typing.Protocol` ONLY. Never `ABC`, never `abstractmethod`.

**4. `src/ml_clients/dataclasses.py`** — 7 immutable dataclasses:
```python
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass(frozen=True)
class EmbeddingInput:
    text: str
    model_id: str
    instruction_prefix: str | None = None

@dataclass(frozen=True)
class EmbeddingOutput:
    embedding: list[float]
    model_id: str
    dimension: int

@dataclass(frozen=True)
class NERInput:
    text: str
    entity_classes: list[str]
    threshold: float = 0.5

@dataclass(frozen=True)
class EntityMention:
    text: str
    label: str
    start: int
    end: int
    score: float

@dataclass(frozen=True)
class NEROutput:
    mentions: list[EntityMention]

@dataclass(frozen=True)
class ExtractionInput:
    prompt: str
    context: str
    output_schema: dict
    model_id: str
    template_id: str | None = None

@dataclass(frozen=True)
class ExtractionOutput:
    result: dict
    raw_response: str
    model_id: str
    extraction_confidence: float | None = None
```

**5. `src/ml_clients/errors.py`** — re-export only (no new error types):
```python
from messaging.kafka.consumer.errors import RetryableError, FatalError
__all__ = ["RetryableError", "FatalError"]
```

**6. `src/ml_clients/config.py`**:
```python
from pydantic_settings import BaseSettings

class MLClientsSettings(BaseSettings):
    model_config = {"env_prefix": ""}  # No prefix — shared across services

    ollama_base_url: str = "http://ollama:11434"
    embedding_model_id: str = "bge-large-en-v1.5"
    extraction_model_id: str = "qwen2.5:7b-instruct"
    ner_model_path: str = "urchade/gliner_large-v2.1"
    max_ollama_concurrent: int = 4  # asyncio.Semaphore value
```

**7. `src/ml_clients/__init__.py`** — export all public symbols.

**Validation gate** (after T-F-004):
```bash
cd libs/ml-clients
ruff check src/
mypy --strict src/
python -m pytest tests/test_protocols.py -v
```

---

### T-F-005 — Concrete adapters

Create 4 adapter modules in `libs/ml-clients/src/ml_clients/adapters/`.

**`adapters/ollama_embedding.py`**:
```python
import asyncio
import structlog
import httpx
from ml_clients.protocols import EmbeddingClient
from ml_clients.dataclasses import EmbeddingInput, EmbeddingOutput
from ml_clients.errors import RetryableError, FatalError

logger = structlog.get_logger()

class OllamaEmbeddingAdapter:
    """Implements EmbeddingClient via Ollama REST API. Model: bge-large-en-v1.5 (1024-dim)."""

    EXPECTED_DIMENSION = 1024
    MODEL_ID = "bge-large-en-v1.5"

    def __init__(self, base_url: str, model_id: str, semaphore: asyncio.Semaphore) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_id = model_id
        self._semaphore = semaphore

    async def embed(self, inputs: list[EmbeddingInput]) -> list[EmbeddingOutput]:
        results: list[EmbeddingOutput] = []
        for inp in inputs:
            async with self._semaphore:
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        text = f"{inp.instruction_prefix} {inp.text}" if inp.instruction_prefix else inp.text
                        resp = await client.post(
                            f"{self._base_url}/api/embeddings",
                            json={"model": self._model_id, "prompt": text}
                        )
                        resp.raise_for_status()
                        embedding = resp.json()["embedding"]
                        if len(embedding) != self.EXPECTED_DIMENSION:
                            raise FatalError(
                                f"Unexpected embedding dimension: {len(embedding)} (expected {self.EXPECTED_DIMENSION})"
                            )
                        results.append(EmbeddingOutput(
                            embedding=embedding,
                            model_id=self._model_id,
                            dimension=len(embedding)
                        ))
                        logger.info("embedding_generated", model_id=self._model_id, dimension=len(embedding))
                except httpx.TimeoutException as exc:
                    raise RetryableError(f"Ollama embedding timeout: {exc}") from exc
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code >= 500:
                        raise RetryableError(f"Ollama 5xx: {exc}") from exc
                    raise FatalError(f"Ollama 4xx: {exc}") from exc
                except FatalError:
                    raise
                except Exception as exc:
                    raise FatalError(f"Unexpected embedding error: {exc}") from exc
        return results
```

Verify `isinstance(OllamaEmbeddingAdapter(...), EmbeddingClient)` returns True (Protocol compliance check).

**`adapters/ollama_extraction.py`**:
- Same error mapping pattern as above
- Calls `POST {base_url}/api/chat` with system prompt + user prompt
- Parses JSON from the model response using `json.loads`
- If JSON parse fails → `FatalError("malformed extraction output")`
- Logs `model_id` on every call via structlog

**`adapters/gliner_local.py`**:
- Constructor: `(model_path: str, semaphore: asyncio.Semaphore)`
- The GLiNER model load must happen in `__init__` (lazy load on first call is acceptable but must be thread-safe)
- `extract_entities(inp)` wraps `gliner_model.predict_entities(inp.text, inp.entity_classes, threshold=inp.threshold)` in `asyncio.get_event_loop().run_in_executor(None, sync_call)` — NEVER call sync GLiNER directly in an async method
- Apply NMS (non-maximum suppression): after getting spans, sort by score desc, discard any span with IoU > 0.5 against a higher-scored kept span
- Error mapping: `MemoryError` / `RuntimeError` → `RetryableError`; `ValueError` → `FatalError`

**`adapters/anthropic_extraction.py`**:
- Constructor: `(api_key: str, model_id: str, semaphore: asyncio.Semaphore)`. Default model: `claude-sonnet-4-6`.
- Uses `anthropic.AsyncAnthropic(api_key=api_key)` (imported conditionally: `try: import anthropic except ImportError: anthropic = None`)
- If anthropic not installed → raise `FatalError("anthropic package not installed; install ml-clients[anthropic]")`
- Error mapping: `anthropic.RateLimitError` → `RetryableError`; `anthropic.APIConnectionError` → `RetryableError`; `anthropic.BadRequestError` → `FatalError`

**`adapters/__init__.py`** — export all 4 adapters.

**Validation gate** (after T-F-005):
```bash
cd libs/ml-clients
ruff check src/
mypy --strict src/
python -m pytest tests/ --ignore=tests/integration/ -v
```

---

### T-F-006 — Tests + documentation

**Test files to create**:

**`tests/conftest.py`**:
```python
import asyncio
import pytest

@pytest.fixture
def semaphore() -> asyncio.Semaphore:
    return asyncio.Semaphore(10)
```

**`tests/test_protocols.py`** — Protocol compliance matrix:
```python
import asyncio
import pytest
from ml_clients.protocols import EmbeddingClient, NERClient, ExtractionClient
from ml_clients.dataclasses import EmbeddingInput, EmbeddingOutput, NERInput, NEROutput, ExtractionInput, ExtractionOutput

class MockEmbeddingClient:
    async def embed(self, inputs: list[EmbeddingInput]) -> list[EmbeddingOutput]:
        return []

class BadEmbeddingClient:
    def embed(self, inputs):  # Missing async
        return []

def test_embedding_protocol_isinstance():
    assert isinstance(MockEmbeddingClient(), EmbeddingClient)

def test_bad_client_fails_protocol():
    # Static type check catches this; runtime isinstance still passes (protocol is structural)
    # Document the limitation: runtime_checkable only checks method presence, not signature
    pass  # Type test via mypy

def test_frozen_dataclass_immutable():
    inp = EmbeddingInput(text="hello", model_id="bge")
    with pytest.raises(Exception):  # FrozenInstanceError
        inp.text = "world"  # type: ignore[misc]
```

**`tests/test_adapters.py`** — adapter unit tests using mocks:
- `OllamaEmbeddingAdapter`: mock `httpx.AsyncClient.post`; test (a) timeout → RetryableError, (b) 500 → RetryableError, (c) 400 → FatalError, (d) valid response → EmbeddingOutput with dimension=1024, (e) wrong dimension → FatalError
- `OllamaExtractionAdapter`: test malformed JSON response → FatalError
- `GLiNERLocalAdapter`: mock `asyncio.get_event_loop().run_in_executor`; test MemoryError → RetryableError
- `AnthropicExtractionAdapter`: mock `anthropic.AsyncAnthropic`; test RateLimitError → RetryableError

**`tests/integration/__init__.py`** and **`tests/integration/test_ollama_integration.py`**:
```python
import pytest

@pytest.mark.integration
async def test_ollama_embedding_roundtrip(semaphore):
    """Requires OLLAMA_BASE_URL env var and bge-large-en-v1.5 model loaded."""
    import os
    from ml_clients.adapters.ollama_embedding import OllamaEmbeddingAdapter
    from ml_clients.dataclasses import EmbeddingInput
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    adapter = OllamaEmbeddingAdapter(base_url=base_url, model_id="bge-large-en-v1.5", semaphore=semaphore)
    result = await adapter.embed([EmbeddingInput(text="Apple Inc. reported earnings", model_id="bge-large-en-v1.5")])
    assert len(result) == 1
    assert result[0].dimension == 1024
    assert len(result[0].embedding) == 1024
```

**`docs/libs/ml-clients.md`** — complete library documentation meeting all 8 quality criteria:

Structure:
1. Overview (what the lib does, why Protocol over ABC, the no-naked-exceptions rule)
2. Protocol table (3 rows: EmbeddingClient, NERClient, ExtractionClient — method, used-by)
3. Dataclass table (7 dataclasses with fields)
4. Adapter table (4 adapters: protocol, backend, model version, optional dep)
5. Configuration section (5 ENV vars)
6. **Sequence diagram** (mermaid): how S6 calls `OllamaEmbeddingAdapter.embed()` → Ollama → returns `EmbeddingOutput`
7. **Code example**: complete FastAPI lifespan injection of `OllamaEmbeddingAdapter`
8. **Common pitfalls section** (≥ 4 concrete pitfalls):
   - Calling GLiNER synchronously inside an async handler (blocks event loop)
   - Constructing an adapter without a semaphore (unbounded concurrency → OOM Ollama)
   - Catching raw exceptions instead of re-raising as RetryableError/FatalError
   - Importing from adapter modules directly instead of coding to Protocol interface
9. Testing section: how to run unit vs integration tests

**Validation gate** (after T-F-006):
```bash
cd libs/ml-clients
python -m pytest tests/ --ignore=tests/integration/ -v --tb=short
ruff check src/ tests/
mypy --strict src/
```

## Constraints

- Do NOT implement any application logic for S6 or S7 — this library is protocol definitions and adapters only.
- Do NOT depend on any external service in unit tests (mock everything). Integration tests are the only place where real Ollama is contacted.
- Do NOT use `ABC` or `abstractmethod` anywhere in `libs/ml-clients` — `typing.Protocol` only.
- Do NOT add mandatory dependencies that require a GPU or large model download. `gliner` and `anthropic` are optional extras only.
- Do NOT write ml-clients tests that import from service directories (`services/`).

## Scope & token budget

**write_paths**:
```
libs/ml-clients/pyproject.toml
libs/ml-clients/src/ml_clients/__init__.py
libs/ml-clients/src/ml_clients/protocols.py
libs/ml-clients/src/ml_clients/dataclasses.py
libs/ml-clients/src/ml_clients/errors.py
libs/ml-clients/src/ml_clients/config.py
libs/ml-clients/src/ml_clients/adapters/__init__.py
libs/ml-clients/src/ml_clients/adapters/ollama_embedding.py
libs/ml-clients/src/ml_clients/adapters/ollama_extraction.py
libs/ml-clients/src/ml_clients/adapters/gliner_local.py
libs/ml-clients/src/ml_clients/adapters/anthropic_extraction.py
libs/ml-clients/tests/__init__.py
libs/ml-clients/tests/conftest.py
libs/ml-clients/tests/test_protocols.py
libs/ml-clients/tests/test_adapters.py
libs/ml-clients/tests/integration/__init__.py
libs/ml-clients/tests/integration/test_ollama_integration.py
docs/libs/ml-clients.md
```

**Exploration bound**: Read at most 5 files from `libs/` before starting implementation (for pyproject.toml and error class patterns). The response document contains all spec detail needed.

## Required tests

```bash
# Unit tests (CI gate — must pass):
cd libs/ml-clients && python -m pytest tests/ --ignore=tests/integration/ -v --tb=short

# Type checking:
mypy --strict libs/ml-clients/src/

# Lint:
ruff check libs/ml-clients/src/ libs/ml-clients/tests/

# Integration tests (skip in CI, run manually with Ollama):
# RUN_INTEGRATION_TESTS=1 pytest tests/integration/ -v -m integration
```

**Pass criteria**:
- All unit tests: 100% pass
- mypy --strict: zero errors on `libs/ml-clients/src/`
- ruff check: zero errors
- Protocol isinstance checks: `isinstance(OllamaEmbeddingAdapter(...), EmbeddingClient)` returns True
- All adapters catch exceptions and re-raise as RetryableError or FatalError only

## Incremental quality gates (mandatory)

**After T-F-004** (scaffold + protocols + dataclasses):
```bash
cd libs/ml-clients
ruff check src/ml_clients/protocols.py src/ml_clients/dataclasses.py src/ml_clients/config.py src/ml_clients/errors.py
mypy --strict src/ml_clients/protocols.py src/ml_clients/dataclasses.py src/ml_clients/config.py
python -m pytest tests/test_protocols.py -v
```

**After T-F-005** (adapters):
```bash
cd libs/ml-clients
ruff check src/ml_clients/adapters/
mypy --strict src/ml_clients/adapters/
python -m pytest tests/test_adapters.py -v
```

**After T-F-006** (tests + docs):
```bash
cd libs/ml-clients
python -m pytest tests/ --ignore=tests/integration/ -v --tb=short
ruff check tests/
# Verify docs/libs/ml-clients.md exists and has all required sections
python -c "
content = open('../../docs/libs/ml-clients.md').read()
for section in ['## Common Pitfalls', '## Configuration', 'mermaid', 'async def']:
    assert section in content, f'Missing section: {section}'
print('Documentation structure OK')
"
```

**No Deferred Fixes**: If any gate fails, fix immediately before moving to the next task.

## Documentation requirements

**Files to create or update in this wave**:
- `docs/libs/ml-clients.md` — **new, complete documentation file** (primary output of T-F-006)

**Documentation quality standard** — all 8 criteria must be met:
1. **Accuracy**: every ENV var, protocol method signature, adapter backend URL must match the implementation
2. **Diagrams**: mermaid sequence diagram for `S6 → OllamaEmbeddingAdapter → Ollama → EmbeddingOutput` flow
3. **Realistic code examples**: complete FastAPI lifespan snippet showing adapter construction and DI
4. **Abstract methods documented**: N/A (no abstract classes; Protocol methods listed in protocol table)
5. **Common pitfalls section**: ≥ 4 concrete pitfalls with consequences
6. **Lib docs updated**: `docs/libs/ml-clients.md` is the new lib doc (created in this wave)
7. **Service docs reflect final state**: N/A (no service modified in this wave)
8. **No orphan documentation**: all documented symbols must exist in the implementation

## Required handoff evidence

1. **Changed files list**
2. **Validation ledger**:
   | Command | Scope | Exit code | Result |
   |---------|-------|-----------|--------|
   | `python -m pytest tests/ --ignore=tests/integration/ -v` | libs/ml-clients | 0 | ✓ |
   | `mypy --strict src/` | libs/ml-clients | 0 | ✓ |
   | `ruff check src/ tests/` | libs/ml-clients | 0 | ✓ |
   | `isinstance(OllamaEmbeddingAdapter(...), EmbeddingClient)` | protocol check | True | ✓ |

3. **Documentation quality checklist**:
   | Criterion | Status | Notes |
   |-----------|--------|-------|
   | Accuracy verified | ✓ | All fields match implementation |
   | Diagrams added for non-trivial flows | ✓ | S6 → adapter → Ollama sequence diagram |
   | Realistic code examples | ✓ | FastAPI lifespan injection example |
   | Abstract methods documented | N/A | No abstract classes; Protocol table provided |
   | Common pitfalls section present | ✓ | 4 pitfalls listed |
   | Lib docs updated | ✓ | docs/libs/ml-clients.md created |
   | Service docs reflect final state | N/A | No service changed |
   | No orphan documentation | ✓ | |

4. **Commit message proposal**:
   ```
   feat(libs): add ml-clients as sixth shared library

   Implement EmbeddingClient, NERClient, and ExtractionClient protocols (structural
   typing); OllamaEmbeddingAdapter, OllamaExtractionAdapter, GLiNERLocalAdapter, and
   AnthropicExtractionAdapter concrete adapters with semaphore injection and strict
   RetryableError/FatalError error hierarchy; full unit test suite; docs/libs/ml-clients.md.
   ```

## Definition of done

- [ ] `libs/ml-clients/` exists as a complete Hatch library scaffold
- [ ] 3 Protocol classes defined with `typing.Protocol` (NOT ABC)
- [ ] 7 frozen dataclasses in `dataclasses.py`
- [ ] `errors.py` re-exports `RetryableError` + `FatalError` from `libs/messaging`
- [ ] 4 concrete adapter classes fully implemented
- [ ] All adapters raise ONLY `RetryableError` or `FatalError` (no naked exceptions)
- [ ] `asyncio.Semaphore` injected at construction and acquired before every ML call
- [ ] GLiNER calls wrapped in `run_in_executor` (never blocks event loop)
- [ ] Unit tests: ≥ 4 test cases per adapter covering timeout, 5xx, 4xx, success paths
- [ ] Protocol compliance tests: all 3 protocols pass `isinstance` check
- [ ] `mypy --strict` passes on all `src/` files
- [ ] `ruff check` passes on all `src/` and `tests/` files
- [ ] Integration test stubs exist in `tests/integration/` (marked `@pytest.mark.integration`)
- [ ] `docs/libs/ml-clients.md` created and meets all 8 quality criteria
- [ ] Documentation quality checklist completed (all 8 criteria ✓ or explicitly N/A)
- [ ] Incremental quality gates passed for each task (no deferred failures)
- [ ] Commit message proposal provided
