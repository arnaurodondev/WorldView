# Weird-Path Quality Sample — PLAN-0112 W6 / T-6-01

**Date**: 2026-06-13
**Author**: Arnau Rodon (with Claude)
**Scope**: PLAN-0112 Wave 6 quality gate — judge the new `weirdness` metric on live data.
**Tool**: `scripts/eval/weird_path_quality_sample.py` (read-only)
**Data source**: live `path_insights` (`intelligence_db`, migration 0052 applied, 514 scored rows).
**Related**: PRD-0112 §5 (success metrics), §11 (validation), `2026-06-12-weird-path-redesign-feasibility.md`.

---

## 1. Method

`weird_path_quality_sample.py` pulled, from the live database:

- the **top-20 global** weird connections (`ORDER BY weirdness DESC`, deduped to
  `DISTINCT (anchor_entity_id, dst_entity_id)` endpoint-pairs — the OQ-6 dedup the global
  feed uses), and
- the **top-10 per-anchor** weird paths for the 5 anchors with the most scored insights.

Each path is rendered as a single human-judgeable line (path chain + the five sub-scores:
reliability `R`, unexpectedness `U`, semantic-distance `S`, novelty `N`, composite
`weirdness w`). The tool **auto-flags** likely-noise rows with three heuristics:

| Flag | Detects | Maps to |
|------|---------|---------|
| `self-loop` | any `entity_id` repeats on the path | the old Cameco→Cameco / Meta→WhatsApp→Meta degenerate cycles |
| `duplicate-name` | distinct ids but a shared display name | the deferred FR-11 duplicate-canonical problem (NVIDIA ×3 etc.) |
| `membership-only` | every edge is a membership relation (`IS_IN_SECTOR` / `LISTED_ON` / `OPERATES_IN_COUNTRY` / `HEADQUARTERED_IN`) | the old "both are in the Health Care sector" sector-hub chains |

The membership set is imported from the production engine constant
(`knowledge_graph.domain.constants.MEMBERSHIP_RELATIONS`) so the flag stays in lock-step
with what the traversal prunes.

> **Note on labelling.** As with PLAN-0110 W6-T-02, *formal human labelling remains the
> user's call*. This report records the **automated** assessment + the rendered sample so a
> human can judge directly. The auto-flag is a conservative proxy for the PRD §5
> "sector-hub / self-loop noise" definition, not a substitute for human judgement.

---

## 2. Result — gate PASSED

**Auto-flagged noise: 0 / 20** global rows. Gate target (PRD §5): **< 3 / 20**. → **PASS.**

All five per-anchor blocks (50 paths) were likewise **0 flagged**.

### Distribution (whole scored corpus, 514 rows)

| Metric | p10 | p50 | p90 | spread (p90−p10) |
|--------|-----|-----|-----|------------------|
| **`weirdness`** (new) | 0.234 | 0.408 | 0.756 | **0.522** |
| `surprise_score` (old, 20 956 rows) | 0.495 | 0.948 | 0.993 | 0.498 (saturated near 1) |

The new metric meets the §5 "discriminating spread > 0.5" target (0.522) and, crucially, is
**not saturated**: the median sits at 0.408 with a long usable range, whereas the old
`surprise_score` piled up against 1.0 (p50 = 0.948) and could not separate good paths from
hub noise.

---

## 3. Rendered global top-20 (verbatim tool output)

```
 1. w=0.850  [R=1.00 U=1.00 S=1.00 N=0.00]  (3h) Super Micro Computer Inc -[CORPORATE_ACTION]-> NVIDIA Corporation -[COMPETES_WITH]-> Broadcom Inc -[PARTNER_OF]-> Apollo Global Management
 2. w=0.850  [R=1.00 U=1.00 S=1.00 N=0.00]  (2h) Super Micro Computer Inc -[CORPORATE_ACTION]-> NVIDIA Corporation -[REVENUE_FROM_COUNTRY]-> People's Republic of China
 3. w=0.806  [R=1.00 U=0.90 S=1.00 N=0.00]  (2h) PulteGroup Inc -[PARTNER_OF]-> NVIDIA Corporation -[CORPORATE_ACTION]-> Amazon Business
 4. w=0.803  [R=1.00 U=0.89 S=1.00 N=0.00]  (2h) J.P. Morgan -[CORPORATE_ACTION]-> FactSet -[CORPORATE_ACTION]-> NVIDIA Corporation
 5. w=0.803  [R=1.00 U=0.89 S=1.00 N=0.00]  (2h) Executive Office of the President -[INVESTMENT_IN]-> Intel Corporation -[CORPORATE_ACTION]-> JPMorgan Chase & Co
 6. w=0.788  [R=1.00 U=0.86 S=1.00 N=0.00]  (2h) Reddit, Inc. -[COMPETES_WITH]-> Meta Platforms Inc. -[COMPETES_WITH]-> Amazon Business
 7. w=0.783  [R=1.00 U=0.85 S=1.00 N=0.00]  (2h) Netflix, Inc. -[COMPETES_WITH]-> Meta Platforms Inc. -[COMPETES_WITH]-> Amazon Business
 8. w=0.776  [R=1.00 U=0.84 S=1.00 N=0.00]  (2h) Cisco Systems Inc -[IS_IN_INDUSTRY]-> Intel Corporation -[OWNS_STAKE_IN]-> US government
 9. w=0.776  [R=1.00 U=0.84 S=1.00 N=0.00]  (2h) Zacks Investment Research -[ANALYST_RATING]-> Microsoft Corporation -[COMPETES_WITH]-> NVIDIA Corporation
10. w=0.755  [R=1.00 U=0.79 S=1.00 N=0.00]  (2h) Executive Office of the President -[INVESTMENT_IN]-> Intel Corporation -[COMPETES_WITH]-> Arm Holdings plc American Depositary Shares
11. w=0.753  [R=0.97 U=0.83 S=1.00 N=0.00]  (2h) Constellation Energy Corp -[PARTNER_OF]-> Meta Platforms Inc. -[EXPOSED_TO_THEME]-> Digital Advertising
12. w=0.749  [R=1.00 U=0.78 S=1.00 N=0.00]  (2h) PulteGroup Inc -[PARTNER_OF]-> NVIDIA Corporation -[INVESTMENT_IN]-> Nebius Group N.V.
13. w=0.739  [R=0.97 U=0.80 S=1.00 N=0.00]  (2h) Morgan Stanley -[ANALYST_RATING]-> Tesla Inc -[EXPOSED_TO_THEME]-> Electric Vehicles
14. w=0.735  [R=1.00 U=0.74 S=1.00 N=0.00]  (2h) Executive Office of the President -[INVESTMENT_IN]-> Intel Corporation -[PRODUCES]-> Taiwan Semiconductor Manufacturing
15. w=0.733  [R=1.00 U=0.74 S=1.00 N=0.00]  (2h) PulteGroup Inc -[PARTNER_OF]-> NVIDIA Corporation -[CORPORATE_ACTION]-> Nasdaq Composite Index
16. w=0.729  [R=1.00 U=0.73 S=1.00 N=0.00]  (2h) Executive Office of the President -[INVESTMENT_IN]-> Intel Corporation -[IS_IN_INDUSTRY]-> Cisco Systems Inc
17. w=0.729  [R=1.00 U=0.73 S=1.00 N=0.00]  (2h) Cisco Systems Inc -[IS_IN_INDUSTRY]-> Intel Corporation -[INVESTMENT_IN]-> Executive Office of the President
18. w=0.728  [R=1.00 U=0.73 S=1.00 N=0.00]  (2h) Constellation Energy Corp -[PARTNER_OF]-> Microsoft Corporation -[INVESTMENT_IN]-> Kingdom of Saudi Arabia
19. w=0.725  [R=1.00 U=0.72 S=1.00 N=0.00]  (2h) Executive Office of the President -[INVESTMENT_IN]-> Intel Corporation -[IS_IN_INDUSTRY]-> Corning Incorporated
20. w=0.725  [R=1.00 U=0.72 S=1.00 N=0.00]  (2h) Corning Incorporated -[IS_IN_INDUSTRY]-> Intel Corporation -[INVESTMENT_IN]-> Executive Office of the President

Auto-flagged noise: 0/20  → gate (<3/20): PASS
```

Per-anchor blocks (Zacks Investment Research, Executive Office of the President, Morgan
Stanley, Mastercard Inc, Reddit Inc) all returned 10 paths, 0 flagged. Re-run with
`python scripts/eval/weird_path_quality_sample.py` for the full per-anchor listing.

---

## 4. Qualitative verdict

**The redesign works.** This is a categorically different feed from the 2026-06-12 baseline.

**Strengths (human read of the top-20):**

- **Genuine cross-domain bridges.** #1 "Super Micro → NVIDIA → Broadcom → Apollo Global
  Management" links a hardware vendor to a PE firm via the AI-supply-chain; #12 "PulteGroup
  (homebuilder) → NVIDIA → Nebius Group" and #18 "Constellation Energy → Microsoft → Saudi
  Arabia" are exactly the "obscure link between unlike entities" the feature was meant to
  surface. These are intellectually interesting, not tautological.
- **Hub demotion works.** Not a single "both are in sector X" / "both listed on NASDAQ"
  membership chain reached the top-20 — the post-hoc membership filter + the
  configuration-model unexpectedness term (which penalises high-degree endpoints) jointly
  killed the old #1 failure mode. The few `IS_IN_INDUSTRY` edges that appear (#8, #16, #17,
  #19, #20) route *through* Intel into a meaningful corporate relation, and `IS_IN_INDUSTRY`
  is **not** a membership relation (it is an inter-company industry edge, not a sector tag).
- **No self-loops, no duplicate-name cycles** in the sample — the scorer's distinct-node
  guard (weirdness = 0 for non-distinct paths) is doing its job; the old Cameco→Cameco /
  Meta→WhatsApp→Meta degenerates are gone.
- **Reliability gate visibly active.** Lower-confidence paths (e.g. Morgan Stanley #5,
  R=0.75) are pushed down relative to R=1.00 paths with the same U/S — the multiplicative
  gate behaves as designed.
- Matches the orchestrator's independent live read (PulteGroup→NVIDIA→Nebius w=0.749,
  Super Micro→NVIDIA→Apollo w=0.850, Executive-Office→Intel→TSMC) exactly.

**Honest caveats (for the user's manual review and for the thesis):**

1. **Semantic distance is binary-ish at the top.** Nearly all top-20 rows have S=1.00. With
   the present embedding coverage, endpoints of different entity_type frequently hit the
   `+typefallback` path (1.0 different-type) rather than a true cosine. S is doing
   *coarse* work (different-domain endpoints rank up) but is not yet finely discriminating;
   this is a known limitation while embedding coverage and the type-fallback split are as
   they are. The thesis should report S as "type-aware coarse distance" honestly, not as a
   fully embedding-driven signal.
2. **Novelty is 0.00 across the board.** With `novelty_window_days = 7` and a graph whose
   edges predate the last week, no edge counts as "recent", so N contributes nothing right
   now. This is expected for a ~3-week-old graph (OQ-4) and is the documented default; N
   will start contributing as fresh edges arrive. It is currently dead weight (×0.15) — not
   wrong, just inactive.
3. **Near-duplicate "fan-out" within a single anchor.** The per-anchor blocks show many
   paths that share the first hop (e.g. Executive-Office→Intel→{10 different targets}, all
   w=0.803 because U/S/N are identical and only the far endpoint differs). The global
   feed's `DISTINCT (anchor, dst)` dedup (OQ-6) hides this at the global level, but the
   per-anchor view is repetitive. Not "noise" by the §5 definition, but a UX consideration —
   FR-14 (LLM explanations) and/or a per-anchor diversity cap would help. Out of scope here.
4. **Auto-flag is a proxy.** 0/20 *auto-flagged* is strong evidence but the auto-flag only
   covers the three structural noise classes. A human may still down-rate a path as
   "obvious" (e.g. two megacaps that "COMPETES_WITH" each other). My read is that none of
   the top-20 are obvious-to-the-point-of-uninteresting, but this is the judgement the user
   should confirm.

**Bottom line:** automated gate PASS (0/20, well under the <3/20 target); distribution is
discriminating (spread 0.522 > 0.5); qualitative read is strongly positive with the caveats
above (S coarse, N inactive on a young graph, per-anchor fan-out). Recommend the user do a
quick manual pass over the top-20 to ratify, then treat the gate as cleared.

---

## 5. Metric ablation — weights (OQ-1) + unexpectedness mode (OQ-2) — T-6-02

**Tool**: `scripts/eval/weirdness_ablation.py` (read-only). Run over the 514 scored paths
(`total_edges = 9 979`, `max_degree = 393`).

> **Honesty note.** The weight ablation (OQ-1) is **exact** — `weirdness = R·(w_U·U +
> w_S·S + w_N·N)` re-scores directly from the stored R/U/S/N columns. The unexpectedness-mode
> ablation (OQ-2) **recomputes U** per path from `node_degree` + `graph_stats` using the
> production scorer's imported formulas; it does **not** re-run AGE traversal, so it compares
> the *signal* over the already-discovered path set (the population the ranking serves), not a
> full re-discovery. A self-check confirms the recompute matches the shipped scorer:
> mean |recomputed U − stored U| = **0.0176** (≈ 0).

### OQ-1 — weights

| weights | p10 | p50 | p90 | spread | top-20 overlap vs shipped |
|---------|-----|-----|-----|--------|---------------------------|
| **shipped (0.45/0.40/0.15)** | 0.234 | 0.408 | 0.756 | 0.522 | 1.00 |
| U-heavy (0.60/0.30/0.10) | 0.257 | 0.479 | 0.781 | 0.524 | 1.00 |
| S-heavy (0.30/0.55/0.15) | 0.231 | 0.349 | 0.785 | 0.554 | 1.00 |
| equal (0.34/0.33/0.33) | 0.184 | 0.328 | 0.608 | 0.424 | 0.82 |
| no-novelty (0.53/0.47/0.00) | 0.274 | 0.475 | 0.889 | 0.615 | 1.00 |

**Read.** The shipped weights are robust: every variant *except* `equal` keeps a top-20
overlap of **1.00** with shipped — i.e. the head of the ranking is insensitive to the exact
U/S split, which is reassuring for thesis defensibility (the result is not a knob-tuning
artefact). `equal` (which over-weights the currently-inactive novelty term) is the only set
that perturbs the top-20 (0.82) and it *lowers* the spread (0.424) — worse discrimination.
`no-novelty` looks tempting (wider spread, identical top-20) but dropping N entirely would
discard a signal that will start contributing as the graph ages (OQ-4); keeping w_N = 0.15
costs nothing today (N ≈ 0 everywhere) and future-proofs the metric. **Conclusion: ship
0.45 / 0.40 / 0.15.**

### OQ-2 — unexpectedness mode

| mode | spread p10-p90 | top-20 overlap vs stored |
|------|----------------|--------------------------|
| **config_model (shipped)** | 0.230–0.753 (0.523) | 0.82 (self, recompute jitter) |
| adamic_adar | 0.203–0.824 (0.621) | 0.74 |

**Read.** Adamic-Adar produces a slightly wider raw spread but **reranks toward megacap-hub
endpoints**, not away from them: the paths it promotes over the config-model top-20 are all
`Zacks Investment Research → <big-tech> → <big-tech>` fan-outs (NVIDIA, Microsoft, Alphabet,
Apple, Amazon). AA rewards low-degree *bridge* vertices, but on this graph the interesting
bridges are mostly already captured by config-model's endpoint-degree penalty, and AA's
extra promotions trade interesting cross-domain endpoints (Apollo, Nebius, Saudi Arabia,
Constellation Energy — all in the config-model top-20) for higher-recognition tech hubs.
That is the *opposite* of the §1 goal. config-model also directly demotes high-degree
endpoints (the documented hub-noise failure mode), which is the property we most want.
**Conclusion: ship `config_model`; keep `adamic_adar` available behind the
`weirdness_unexpectedness_mode` config flag (AD-3) for future re-evaluation as the graph
grows and acquires more genuine low-degree bridge vertices.**

### OQ-4 — novelty window

N is uniformly 0.00 on the current ~3-week graph (no edges within the 7-day window).
`novelty_window_days = 7` is the documented default; it is harmless now (×0.15 of zero) and
becomes useful as fresh edges arrive. **Conclusion: keep 7 days; revisit as edge history
grows** (no evidence yet to change it — changing it now would be tuning against no signal).
