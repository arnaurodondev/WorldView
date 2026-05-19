# prompts

Single source of truth for all LLM prompt templates across the worldview platform.

Prevents prompt drift, enables versioning, and ensures safety controls
(XML-wrapping, SAFETY_FOOTER) are applied consistently. Zero runtime dependencies.

See [docs/libs/prompts.md](../../docs/libs/prompts.md) for full documentation.

## Install (editable, for development)

```bash
pip install -e ".[dev]"
```

## Run tests

```bash
python -m pytest tests/ -v
```
