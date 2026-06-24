# Extraction-quality A/B — LLM-as-judge report

Baseline (production): `Qwen/Qwen3-235B-A22B-Instruct-2507`

## Comparison table

| Model | N | Prec | Recall | Adher | Overall | Fab/art | Allowlist viol/art | JSON-fail | API-err | ev | cl | rel | p50 s | p95 s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `openai/gpt-oss-120b` | 2 | 4.5 | 3.0 | 5.0 | **4.167** | 0.5 | 0.0 | 0.0 | 0.0 | 1 | 0.5 | 0 | 15.507 | 22.602 |
| `Qwen/Qwen3-235B-A22B-Instruct-2507` ⭐base | 2 | 4.0 | 3.5 | 3.5 | **3.667** | 0.5 | 0.5 | 0.0 | 0.0 | 1.5 | 1.5 | 2 | 49.211 | 96.479 |
| `meta-llama/Llama-3.3-70B-Instruct` | 2 | 4.0 | 3.5 | 3.5 | **3.667** | 0.5 | 0.5 | 0.0 | 0.0 | 1 | 1.5 | 1 | 14.746 | 19.732 |

## Ranked verdict

1. `openai/gpt-oss-120b` overall=4.167 — **MATCHES baseline** (Δoverall=+0.5); viable swap if latency/cost favourable
2. `Qwen/Qwen3-235B-A22B-Instruct-2507` overall=3.667 — production baseline
3. `meta-llama/Llama-3.3-70B-Instruct` overall=3.667 — **MATCHES baseline** (Δoverall=+0.0); viable swap if latency/cost favourable

> Methodology: scores are 1-5 per dimension from an INDEPENDENT judge (never the model being judged). 'MATCHES' uses a -0.10 overall tolerance (≈2% of the 5-point scale) — tighten for a production go/no-go. Pair the quality verdict with the latency/cost columns for the swap decision.
