# Extraction-quality A/B — LLM-as-judge report

Baseline (production): `Qwen/Qwen3-235B-A22B-Instruct-2507@low`

## Comparison table

| Model | N | Prec | Recall | Adher | Overall | Fab/art | Allowlist viol/art | JSON-fail | API-err | ev | cl | rel | p50 s | p95 s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `openai/gpt-oss-120b@medium` | 20 | 5.0 | 3.8 | 5.0 | **4.6** | 0.0 | 0.0 | 0.0 | 0.0 | 1.1 | 1.3 | 2.3 | 29.433 | 69.616 |
| `Qwen/Qwen3-235B-A22B-Instruct-2507@low` ⭐base | 20 | 4.4 | 3.6 | 4.15 | **4.05** | 0.2 | 0.25 | 0.0 | 0.0 | 2.05 | 1.8 | 3.95 | 30.641 | 65.508 |

## Ranked verdict

1. `openai/gpt-oss-120b@medium` overall=4.6 — **MATCHES baseline** (Δoverall=+0.55); viable swap if latency/cost favourable
2. `Qwen/Qwen3-235B-A22B-Instruct-2507@low` overall=4.05 — production baseline

> Methodology: scores are 1-5 per dimension from an INDEPENDENT judge (never the model being judged). 'MATCHES' uses a -0.10 overall tolerance (≈2% of the 5-point scale) — tighten for a production go/no-go. Pair the quality verdict with the latency/cost columns for the swap decision.
