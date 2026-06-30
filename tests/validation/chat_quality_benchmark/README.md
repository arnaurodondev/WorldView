# Chat Quality Benchmark

Multi-level evaluation harness for the grounded RAG chat (PRD-0091 / PLAN-0110).
The runner (`scripts/run_chat_quality_benchmark.py`) drives each question through
the live chat, captures the SSE trace, and grades each answer with the
deterministic + LLM judge in `scripts/chat_quality_judge.py`. Artefacts land in a
timestamped run directory: per-question `q_<id>[_runN].json`, a machine
`_judge_summary.json`, and a human `_report.md`.

## Substantiation run (MUST-1 / Wave W1)

The **substantiation gate** (W1) is a deterministic, LLM-free cross-check that
asks a stricter question than grounding-contradiction: not only "did the agent
state a number a tool *disproves*?" (that is `GROUNDING_CONTRADICTED`), but also
"did the agent assert a number for a field the tool *sampled* yet never actually
returned a matching value for?". The latter is the `unsupported` class and trips
the `SUBSTANTIATION_UNSUPPORTED` invariant.

The substantiation cross-check can only *bite* on numeric claims it can associate
to a **captured grounding sample**. Those samples are emitted server-side by the
chat only when the eval flag is set, so a substantiation run MUST export:

```bash
export CHAT_EVAL_GROUNDING_SAMPLES=true
```

This flag is read **per-call** from `os.environ` in
`services/rag-chat/.../application/pipeline/sse_emitter.py` (no service restart is
required — flip it and the next request emits samples). When it is unset/false,
no `grounding_sample` blocks are captured, the cross-check runs in `presumed`
mode, and the substantiation check reports all-zero counts (coverage `presumed`):
the gate can never fire, so a flag-off run is byte-identical to the pre-W1
baseline.

### Coverage bound: 10 tools

Grounding samples are produced ONLY for the tools on the server-side
allow-list (`_GROUNDING_FIELD_ALLOWLIST` in `sse_emitter.py`). As of W1 that is
**10 tools** — the financial / intelligence tools that return structured numeric
fields:

| Domain | Tools |
|--------|-------|
| Financial / market | `get_fundamentals_history`, `get_fundamentals_history_batch`, `compare_entities`, `get_price_history`, `screen_universe`, `get_market_movers` |
| Knowledge / intelligence | `search_claims`, `search_entity_relations`, `get_contradictions`, `get_entity_health` |

News, graph-path, and narrative tools render their numbers into prose `text`
rather than structured fields, so they produce **no** grounding sample and the
substantiation check returns `None`/`unmatched` for claims drawn from them. This
is an **honest coverage bound**, not a silent gap: substantiation `verified`
coverage is bounded by claims that trace to one of these 10 tools. Everything
outside that set is `presumed` and never penalised.
