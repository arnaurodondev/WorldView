# tools

Shared LLM tool-use registry and type layer for the worldview platform.

Provides `ToolSpec` / `ParameterSpec` (tool definitions), `ToolRegistry` (central
lookup with OpenAI function-calling and system-prompt manifest rendering),
`capability_manifest.yaml` (all 22 platform tools), and canonical response types
(`LLMToolResponse`, `ToolCallBatch`, `ToolUseBlock`) shared between the LLM
provider port and every concrete adapter.

Used exclusively by S8 (RAG/Chat). Rule R29: every registered tool must have a
corresponding entry in `capability_manifest.yaml` — architecture tests enforce this.

See [docs/libs/tools.md](../../docs/libs/tools.md) for full documentation.

## Install (editable, for development)

```bash
pip install -e "libs/tools"
pip install -e "libs/tools[dev]"  # includes pytest, ruff, mypy
```

## Run tests

```bash
cd libs/tools
python -m pytest tests/ -v
