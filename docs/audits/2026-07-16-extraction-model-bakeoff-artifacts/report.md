# Extraction-quality A/B — LLM-as-judge report

Baseline (production): `Qwen/Qwen3-235B-A22B-Instruct-2507@medium`

## Comparison table

| Model | N | Prec | Recall | Adher | Overall | Fab/art | Allowlist viol/art | JSON-fail | API-err | ev | cl | rel | p50 s | p95 s | $/1k docs | $/mo proj |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `openai/gpt-oss-120b@medium` | 30 | 4.267 | 2.633 | 4.6 | **3.833** | 0.133 | 0.1 | 0.0 | 0.0 | 1.57 | 1.63 | 2.47 | 57.34 | 93.099 | $0.546 | $73.7 |
| `openai/gpt-oss-120b@low` | 30 | 4.367 | 2.1 | 4.833 | **3.767** | 0.233 | 0.067 | 0.0 | 0.0 | 0.6 | 0.17 | 2.13 | 13.538 | 32.306 | $0.2918 | $39.39 |
| `Qwen/Qwen2.5-72B-Instruct` | 30 | 3.867 | 2.567 | 4.167 | **3.533** | 1.033 | 0.3 | 0.0 | 0.0 | 0.7 | 1.23 | 3.97 | 46.469 | 64.596 | $2.0663 | $278.96 |
| `deepseek-ai/DeepSeek-V4-Flash` | 30 | 4.0 | 2.7 | 3.833 | **3.511** | 0.833 | 0.3 | 0.0 | 0.0 | 2.23 | 1.27 | 4 | 7.18 | 17.058 | $0.5634 | $76.05 |
| `meta-llama/Llama-3.3-70B-Instruct` | 30 | 3.5 | 2.667 | 3.733 | **3.3** | 1.4 | 0.4 | 0.0 | 0.0 | 1.63 | 2 | 4.1 | 57.669 | 95.4 | $0.7136 | $96.33 |
| `Qwen/Qwen3-235B-A22B-Instruct-2507@none` | 30 | 3.633 | 2.7 | 3.433 | **3.256** | 1.533 | 0.567 | 0.0 | 0.0 | 2.03 | 2.5 | 4.67 | 57.692 | 109.95 | $0.9481 | $128.0 |
| `Qwen/Qwen3-235B-A22B-Instruct-2507@low` | 30 | 3.433 | 2.9 | 3.4 | **3.244** | 2.0 | 0.733 | 0.0 | 0.0 | 2.43 | 2.73 | 5.57 | 74.795 | 130.182 | $1.0437 | $140.9 |
| `Qwen/Qwen3-235B-A22B-Instruct-2507@medium` ⭐base | 30 | 3.233 | 2.8 | 3.067 | **3.033** | 2.133 | 0.667 | 0.0 | 0.0 | 2.2 | 2.67 | 5.9 | 67.649 | 96.402 | $1.0407 | $140.49 |

## Ranked verdict

1. `openai/gpt-oss-120b@medium` overall=3.833 — **MATCHES baseline** (Δoverall=+0.8); viable swap if latency/cost favourable
2. `openai/gpt-oss-120b@low` overall=3.767 — **MATCHES baseline** (Δoverall=+0.734); viable swap if latency/cost favourable
3. `Qwen/Qwen2.5-72B-Instruct` overall=3.533 — **MATCHES baseline** (Δoverall=+0.5); viable swap if latency/cost favourable
4. `deepseek-ai/DeepSeek-V4-Flash` overall=3.511 — **MATCHES baseline** (Δoverall=+0.478); viable swap if latency/cost favourable
5. `meta-llama/Llama-3.3-70B-Instruct` overall=3.3 — **MATCHES baseline** (Δoverall=+0.267); viable swap if latency/cost favourable
6. `Qwen/Qwen3-235B-A22B-Instruct-2507@none` overall=3.256 — **MATCHES baseline** (Δoverall=+0.223); viable swap if latency/cost favourable
7. `Qwen/Qwen3-235B-A22B-Instruct-2507@low` overall=3.244 — **MATCHES baseline** (Δoverall=+0.211); viable swap if latency/cost favourable
8. `Qwen/Qwen3-235B-A22B-Instruct-2507@medium` overall=3.033 — production baseline

> Methodology: scores are 1-5 per dimension from an INDEPENDENT judge (never the model being judged). 'MATCHES' uses a -0.10 overall tolerance (≈2% of the 5-point scale) — tighten for a production go/no-go. Pair the quality verdict with the latency/cost columns for the swap decision.
