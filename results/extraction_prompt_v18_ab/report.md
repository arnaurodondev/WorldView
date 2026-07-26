# Prompt A/B — deep_extraction @1.7 (BASELINE) vs @1.8-trim (CANDIDATE)

- BASELINE : `deep_extraction@1.7#ce2c505fd528`
- CANDIDATE: `deep_extraction@1.8#d3e94f184738`
- Extractor (BOTH arms): `deepseek-ai/DeepSeek-V4-Flash` @ reasoning_effort=medium — no confound
- Judge: `deepseek-ai/DeepSeek-V4-Flash` (same judge both arms → self-preference bias is common-mode, cancels in delta)
- Sample: 50 real full_pipeline news docs — 25 co-mention-heavy / 25 regular

## Precision metrics (post-gate survivors — what reaches the KG)

| metric | BASELINE v1.7 | CANDIDATE v1.8 | Δ |
|---|---|---|---|
| judge precision (supported/emitted) | 1.0 (49/49) | 0.9615 (50/52) | -0.0385 |
| **co-mention FP rate** (FP/emitted) | 0.0 (0) | 0.0 (0) | +0.0000 |
| **direction-inversion rate** (inv/directional) | 0.0 (0/23) | 0.0741 (2/27) | +0.0741 |

## Recall metrics

| metric | BASELINE v1.7 | CANDIDATE v1.8 |
|---|---|---|
| gated relations / doc (yield) | 0.98 (49) | 1.04 (52) |
| articles with ≥1 gated relation | 0.46 (23/50) | 0.46 (23/50) |
| mean judge recall grade (1-5) | 5.0 | 5.0 |

## Deterministic structural defects — PRE-GATE (intrinsic prompt looseness)

| defect (raw, before code gate) | BASELINE v1.7 | CANDIDATE v1.8 |
|---|---|---|
| raw relations emitted | 49 | 52 |
| self-loops | 0 | 0 |
| out-of-vocab predicates | 0 | 0 |
| listed_on → non-exchange | 0 | 0 |

## Token cost per doc (authoritative — DeepInfra usage.prompt_tokens)

| metric | BASELINE v1.7 | CANDIDATE v1.8 | Δ |
|---|---|---|---|
| mean prompt tokens / doc | 5531.5 | 5084.5 | -447.0000 |
| total prompt tokens | 276575 | 254225 | -22350 |
| total completion tokens | 122187 | 126942 | 4755 |
| est. cost / doc (USD) | 0.003699 | 0.003658 | -4.1e-05 |

- judge parse errors: baseline=0 candidate=0
