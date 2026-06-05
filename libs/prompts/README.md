# prompts

Single source of truth for all LLM prompt templates across the worldview platform.

Prevents prompt drift, enables versioning, and ensures safety controls
(XML-wrapping, SAFETY_FOOTER) are applied consistently. Zero runtime dependencies.

`PromptTemplate` semver-validates `version` and computes a 12-char sha256
`content_hash` of the template body at construction; `template.identifier()`
returns `"<name>@<version>#<hash>"` for log lines and judge-artefact persistence.

Namespaces include `briefing`, `chat`, `classification`, `description`,
`extraction`, `knowledge`, `retrieval`, and — as of PLAN-0107 — `evaluation`
(LLM-as-judge rubrics: `CHAT_QUALITY_JUDGE`, `CITATION_JUDGE`).

See [docs/libs/prompts.md](../../docs/libs/prompts.md) for full documentation.

## Install (editable, for development)

```bash
pip install -e ".[dev]"
```

## Run tests

```bash
python -m pytest tests/ -v
```
