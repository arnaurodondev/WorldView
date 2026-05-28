"""Aggregate score gate test (PLAN-0093 G-3 T-G-3-10 / PLAN-0099 W1 T-W1-03).

This is the **final acceptance gate** for the chat-eval regression suite.

PLAN-0099 W1 T-W1-03 — Latency metric redesign
----------------------------------------------
The original gate enforced two end-to-end (E2E) latency invariants:

  * median latency ≤ 30s
  * p99 latency    ≤ 60s

Those are now retired in favour of three responsiveness-centric metrics
plus a relaxed E2E watchdog. The motivation, in one paragraph:

  E2E wall-clock conflates the *user-facing responsiveness* (when did the
  first word appear? how fast did tokens stream?) with *query complexity*
  (how many tools fired? how heavy was the structured-output generation?).
  A 3-tool screener-then-fundamentals query legitimately takes 60-80s and
  is not a UX regression; punishing it with a hard p99 gate makes the
  suite red on legitimate model behaviour. Conversely, a slow classifier
  or a degraded LLM provider can silently hide inside a "fast" E2E if
  tools happen to be quick. The new metrics decouple these signals.

New gates (PLAN-0099 W1 T-W1-03 — replace, not augment)
-------------------------------------------------------
| Metric          | Aggregation | Gate     | Rationale                              |
| --------------- | ----------- | -------- | -------------------------------------- |
| ``ttft_s``      | p95         | < 5.0  s | "Did the user see the model start?"    |
| ``tps``         | p50 (median)| ≥ 30   /s| "Is the stream readable speed?"        |
| ``latency_s``   | p99         | < 90.0 s | Watchdog: catches tool hang / outage   |

Verdict gates from PLAN-0093 are unchanged:

  * USEFUL ≥ 6 of 8 audit questions
  * HARMFUL = 0

The median-E2E gate is demoted to a *soft watchdog* (logged, doesn't
fail) — if it ever fires alongside passing TTFT/TPS gates, the cause is
almost certainly tool-fan-out / data-availability rather than
responsiveness. PLAN-0100 will use the per-phase backend instrumentation
from PLAN-0099 W1 T-W1-03 backend hooks to attribute the wall-clock.

Per-run artefacts written by this harness live at::

    tests/validation/chat_eval/runs/<timestamp>/agg_<qid>.json

Each artefact carries ``ttft_s`` / ``tps`` / ``output_tokens`` alongside
``latency_s`` so a failing gate is reproducible offline.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pytest

from tests.validation.chat_eval.grading import HARMFUL, USEFUL, grade_response
from tests.validation.chat_eval.harness import load_questions

if TYPE_CHECKING:
    from tests.validation.chat_eval.harness import ChatRunResult

# ── PLAN-0099 W1 T-W1-03 acceptance gates ────────────────────────────────────
# TTFT p95: 5s is the user-perceptible "model is thinking" boundary — after
#   classifier + first LLM turn, DeepInfra with a warm cache should clear
#   this comfortably. Tighter than the old p99 gate because tail variance
#   is smaller (the tail is dominated by tool latency, which TTFT excludes).
_TTFT_P95_MAX_S = 5.0

# TPS p50: 30 tokens/s is the lower bound for a "smooth" streaming UX —
#   one token every ~33ms reads as natural text flow. Below 10 tok/s the
#   stream feels stalled. Median (not p99) because the median is the
#   typical user experience; a single slow request shouldn't tank the gate.
_TPS_P50_MIN = 30.0

# E2E p99: 90s is a soft watchdog — a 3-tool query with parallel fan-out +
#   second-turn table generation legitimately runs 60-80s. Beyond 90s we
#   suspect a provider hang or DLQ loop, which is genuinely worth failing.
_E2E_P99_MAX_S = 90.0

# Soft watchdog (logged only — does NOT fail the gate). Kept around so a
# classifier-latency regression that hides inside the (loosened) E2E gate
# still surfaces in the failure message.
_MEDIAN_LATENCY_SOFT_WATCHDOG_S = 30.0

# Verdict gates from PLAN-0093 — unchanged.
_MIN_USEFUL = 6
_MAX_HARMFUL = 0


def _percentile(values: list[float], pct: float) -> float:
    """Tiny linear-interp percentile (no numpy dep)."""
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _finite_only(xs: list[float]) -> list[float]:
    """Drop NaN/inf so a single error-path run cannot poison the percentiles."""
    return [x for x in xs if x is not None and math.isfinite(x)]


def test_aggregate_score_gate(ask: Callable[..., ChatRunResult]) -> None:
    """The chat-eval acceptance gate: verdicts + TTFT-p95 + TPS-p50 + E2E-p99."""
    try:
        questions = load_questions()
    except pytest.skip.Exception:
        raise
    except FileNotFoundError:
        pytest.skip("questions.yaml not found")

    verdicts: list[str] = []
    latencies: list[float] = []
    ttfts: list[float] = []
    tps_values: list[float] = []
    per_question: list[dict[str, Any]] = []

    for q in questions:
        qid = q.get("id", "?")
        prompt = q["prompt"]
        gt = q.get("ground_truth_assertions") or {}
        result = ask(prompt, slot=f"agg_{qid}")
        grade = grade_response(prompt, result, gt)
        verdicts.append(grade["verdict"])
        latencies.append(result.latency_s)
        ttfts.append(result.ttft_s)
        tps_values.append(result.tps)
        per_question.append(
            {
                "id": qid,
                "verdict": grade["verdict"],
                "reasons": grade["reasons"],
                "ttft_s": grade.get("ttft_s"),
                "tps": grade.get("tps"),
                "latency_s": grade.get("latency_s"),
            }
        )

    counts = Counter(verdicts)
    useful_count = counts.get(USEFUL, 0)
    harmful_count = counts.get(HARMFUL, 0)

    # Percentiles — drop nans so a single error-path run doesn't poison them.
    finite_latencies = _finite_only(latencies)
    finite_ttfts = _finite_only(ttfts)
    finite_tps = _finite_only(tps_values)

    median_e2e = statistics.median(finite_latencies) if finite_latencies else 0.0
    p99_e2e = _percentile(finite_latencies, 0.99) if finite_latencies else 0.0
    ttft_p95 = _percentile(finite_ttfts, 0.95) if finite_ttfts else float("nan")
    tps_p50 = statistics.median(finite_tps) if finite_tps else float("nan")

    # Build a single multi-line message so a failure surfaces every metric.
    summary = (
        f"verdicts={counts!r}\n"
        f"USEFUL={useful_count} (need >= {_MIN_USEFUL})\n"
        f"HARMFUL={harmful_count} (need <= {_MAX_HARMFUL})\n"
        f"ttft_p95={ttft_p95:.2f}s (max {_TTFT_P95_MAX_S}s)\n"
        f"tps_p50={tps_p50:.2f} tok/s (min {_TPS_P50_MIN})\n"
        f"e2e_p99_latency={p99_e2e:.2f}s (max {_E2E_P99_MAX_S}s)\n"
        f"median_e2e_latency={median_e2e:.2f}s "
        f"(soft watchdog {_MEDIAN_LATENCY_SOFT_WATCHDOG_S}s)\n"
        f"per_question={per_question!r}"
    )

    # All gates as one assert: the test report will show every failing
    # gate at once instead of bailing on the first.
    failures: list[str] = []
    if useful_count < _MIN_USEFUL:
        failures.append(f"USEFUL count {useful_count} < {_MIN_USEFUL}")
    if harmful_count > _MAX_HARMFUL:
        failures.append(f"HARMFUL count {harmful_count} > {_MAX_HARMFUL}")
    # TTFT p95 hard gate — only enforce when we have any finite samples
    # (a fully-failing run gives all-nan TTFT; the verdict gates above
    # will already catch that case).
    if finite_ttfts and ttft_p95 > _TTFT_P95_MAX_S:
        failures.append(f"TTFT p95 {ttft_p95:.2f}s > {_TTFT_P95_MAX_S}s")
    # TPS p50 hard gate — same finite-samples guard.
    if finite_tps and tps_p50 < _TPS_P50_MIN:
        failures.append(f"TPS p50 {tps_p50:.2f} < {_TPS_P50_MIN}")
    # E2E p99 watchdog (relaxed from 60s → 90s).
    if finite_latencies and p99_e2e > _E2E_P99_MAX_S:
        failures.append(f"E2E p99 latency {p99_e2e:.2f}s > {_E2E_P99_MAX_S}s")

    # Soft watchdog — log via the summary, don't fail the gate. If this
    # fires while the hard gates pass, the bottleneck is almost certainly
    # tool fan-out / data-availability rather than responsiveness.
    if finite_latencies and median_e2e > _MEDIAN_LATENCY_SOFT_WATCHDOG_S:
        # Plain print so it lands in pytest's captured output.
        print(
            f"[soft watchdog] median E2E latency {median_e2e:.2f}s "
            f"> {_MEDIAN_LATENCY_SOFT_WATCHDOG_S}s — "
            f"check tool fan-out and provider warmup."
        )

    assert not failures, f"chat-eval acceptance gate FAILED:\n{summary}\nfailures={failures!r}"
