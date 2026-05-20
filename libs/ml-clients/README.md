# ml-clients

Protocol interfaces and concrete adapters for embedding, NER, structured
extraction, entity description generation, cross-encoder reranking, and LLM
cost tracking.

The **only** path through which services call ML models (DeepInfra, Jina,
GLiNER, Anthropic, Gemini, OpenAI, Ollama, Cohere).

See [docs/libs/ml-clients.md](../../docs/libs/ml-clients.md) for full documentation.

## Install (editable, for development)

```bash
pip install -e ".[dev]"

# With optional backends:
pip install -e ".[gliner]"        # local GLiNER model
pip install -e ".[anthropic]"     # Anthropic Claude
pip install -e ".[gemini]"        # Google Gemini
pip install -e ".[openai]"        # OpenAI-compatible (ChatGPT, DeepSeek, DeepInfra)
```

## Run tests

```bash
python -m pytest tests/ -v
```
