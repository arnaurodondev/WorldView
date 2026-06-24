# Extraction-quality A/B — LLM-as-judge report

Baseline (production): `openai/gpt-oss-20b@low`

## Comparison table

| Model | N | Prec | Recall | Adher | Overall | Fab/art | Allowlist viol/art | JSON-fail | API-err | ev | cl | rel | p50 s | p95 s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `openai/gpt-oss-20b@low` ⭐base | 2 | 4.0 | 2.0 | 5.0 | **3.667** | 0.5 | 0.0 | 0.0 | 0.0 | 0.5 | 0.5 | 0 | 1.635 | 4.868 |
| `deepseek-ai/DeepSeek-V4-Flash` | 2 | None | None | None | **None** | 0.0 | 0.0 | 0.0 | 0.0 | 1.5 | 1 | 1 | 8.731 | 12.042 |

## Ranked verdict

1. `openai/gpt-oss-20b@low` overall=3.667 — production baseline
2. `deepseek-ai/DeepSeek-V4-Flash` overall=None

> Methodology: scores are 1-5 per dimension from an INDEPENDENT judge (never the model being judged). 'MATCHES' uses a -0.10 overall tolerance (≈2% of the 5-point scale) — tighten for a production go/no-go. Pair the quality verdict with the latency/cost columns for the swap decision.
