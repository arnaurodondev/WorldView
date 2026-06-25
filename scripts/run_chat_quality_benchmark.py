#!/usr/bin/env python3
"""Standalone chat-quality benchmark runner.

Why this script exists
----------------------
The existing pytest harness in ``tests/validation/chat_eval/`` is the
acceptance gate (binary pass/fail, percentile-based). When the user simply
wants to *characterise* chat-endpoint quality on a curated question set —
"run these N prompts, capture EVERYTHING, give me a folder to read" — pytest
is too rigid (collection rules, fail-fast, no per-question artifacts unless
you wire them up).

This script is descriptive, not prescriptive:

* It dev-logs into S9 (``/v1/auth/dev-login``) and streams each question
  against ``/v1/chat/stream``.
* For every question it writes three files to the run directory:
    - ``q_<id>.json``       full structured artifact (events, tool calls,
                            metadata, heuristics)
    - ``q_<id>.log``        line-per-event human-readable trace
    - ``q_<id>.error.txt``  full traceback if anything blew up
* At the end it writes ``_summary.json`` + ``_meta.json`` and prints a
  per-category banner to stdout.

Heuristics are advisory flags (``is_empty``, ``is_refusal``,
``must_not_say_hits``, ``tool_overlap_with_expected``) — they do not gate
the exit code. The script exits 0 on any successful end-of-stream and
non-zero only on infrastructure failure (no JWT, connection refused, etc.)
so it is safe to wire into CI as an artifact-producing job.

Usage
-----
    .venv312/bin/python scripts/run_chat_quality_benchmark.py \\
        --base-url http://localhost:8000 \\
        --questions-file tests/validation/chat_quality_benchmark/questions.yaml \\
        --tags real_user,smoke \\
        --out-dir tests/validation/chat_quality_benchmark/runs

See ``docs/services/rag-chat.md`` § "Chat Quality Benchmark" for output
schema and interpretation guide.

Two catalogues (audit 2026-06-11 F9 — reconciliation note)
----------------------------------------------------------
There are two question catalogues and they are NOT duplicates:

* ``tests/validation/chat_eval/questions.yaml`` — the binary ACCEPTANCE GATE
  (pytest, percentile pass/fail). This is the authoritative go/no-go gate.
* ``tests/validation/chat_quality_benchmark/questions/*.yaml`` — this
  EXPLORATORY benchmark's catalogue (rubric-graded, descriptive, per-Q
  artefacts). It characterises quality and surfaces failures; it does not gate
  CI. When the two overlap, the chat_eval gate is authoritative for go/no-go;
  this benchmark is authoritative for the quality narrative.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

# We reuse the existing chat_eval harness for SSE parsing + dev-login. It is
# already battle-tested (handles the JWT-refresh-on-401 dance, multi-line SSE
# data fields, BP-613/619 answer-assembly fallback). Pulling it in means this
# script benefits from every fix that lands there.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "tests" / "validation"))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

# isort: off
from chat_eval.grading import is_refusal  # noqa: E402
from chat_eval.harness import (  # noqa: E402
    ChatRunResult,
    RagChatClient,
    _events_to_result,
    _read_sse_events,
)
from chat_quality_judge import (  # noqa: E402
    VERDICT_MODEL_VERSION,
    JudgeInput,
    Rubric,
    _DEFAULT_JUDGE_MODEL,
    build_input_from_artifact,
    judge_answer,
    summarise_judge_records,
)

# --- W2 trajectory layer ---
# The trajectory / tool-chain judge (Multi-Level Eval Framework W2) is an
# ADDITIVE layer over the answer judge: it grades the agent's PROCESS (its
# ordered tool calls) without ever changing the answer FAIL/PASS verdict. We
# import it here and keep every other touch-point in this runner tagged with the
# same ``# --- W2 trajectory layer ---`` marker so the additive surface is
# trivially auditable.
from chat_trajectory_judge import (  # noqa: E402
    judge_trajectory,
    summarise_trajectory_records,
)

from prompts.evaluation import CHAT_QUALITY_JUDGE  # noqa: E402

# PLAN-0110 W4 — the durable longitudinal trend store + regression detection.
# Lives in its own module so the persistence + diff logic is unit-testable
# without spinning up the whole runner (and without touching the judge).
from chat_quality_trend import (  # noqa: E402
    QuestionRow,
    RunRow,
    TrendStore,
    detect_regressions,
)

# isort: on


# --------------------------------------------------------------------------
# Question loading + filtering
# --------------------------------------------------------------------------


def load_questions(path: Path) -> list[dict[str, Any]]:
    """Decode the YAML question catalogue. Lazy-import PyYAML.

    Supports BOTH legacy single-file mode and the new directory layout
    (PLAN-0107 follow-up): if ``path`` is a directory, load every ``*.yaml``
    file under it in alpha-sorted order and concatenate the lists. The
    directory split lets parallel dataset-author agents each own their own
    file (one for tool coverage, one for safety, etc.) without merge
    conflicts on a single 1000+ line catalogue.

    Schema is unchanged — each file is a top-level list of question dicts.
    Filenames are conventional: ``NN_<purpose>.yaml`` where NN is a sort
    key (00 = legacy, 10/20/30 = new packs) so the load order is stable.
    """
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        print("ERROR: PyYAML not installed. Activate .venv312 first.", file=sys.stderr)
        sys.exit(2)

    if path.is_dir():
        all_qs: list[dict[str, Any]] = []
        files = sorted(path.glob("*.yaml"))
        if not files:
            raise ValueError(f"No *.yaml files found in {path}")
        for f in files:
            raw = yaml.safe_load(f.read_text())
            if not isinstance(raw, list):
                raise ValueError(f"Expected list at top level of {f}, got {type(raw).__name__}")
            all_qs.extend(raw)
        return all_qs

    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, list):
        raise ValueError(f"Expected list at top level of {path}, got {type(raw).__name__}")
    return list(raw)


def filter_questions(
    questions: list[dict[str, Any]],
    *,
    tags: list[str] | None,
    ids: list[str] | None,
) -> list[dict[str, Any]]:
    """Apply --tags / --ids filters. AND across kinds, OR within a kind."""
    out = questions
    if ids:
        ids_set = set(ids)
        out = [q for q in out if q.get("id") in ids_set]
    if tags:
        tags_set = set(tags)
        out = [q for q in out if tags_set.intersection(set(q.get("tags") or []))]
    return out


# --------------------------------------------------------------------------
# Heuristics — descriptive flags per question
# --------------------------------------------------------------------------


def compute_heuristics(q: dict[str, Any], result: ChatRunResult) -> dict[str, Any]:
    """Return a dict of advisory quality flags. No pass/fail decision here.

    PLAN-0099-W4: legacy heuristic fields (expected_entities_mentioned,
    expected_min_words, must_not_say) were removed from the question
    schema — the v2.0 judge ignored them and they generated false WARNs.
    expected_tools moved into ``rubric.expected_tools`` and
    expected_max_latency_s into ``budgets.max_latency_s``. We read from
    the new locations here; the heuristic-bucket fields they fed into
    (entities_mentioned/missing, must_not_say_hits, answer_meets_min_words)
    are no longer emitted.
    """
    answer = result.answer_text or ""
    words = answer.split()

    # v2 schema: expected_tools lives inside the ``rubric:`` block (the only
    # piece of the question the LLM judge actually reads). We keep the
    # heuristic ``tool_overlap`` diagnostic so the artefact still shows which
    # of the suggested tools were actually called — it's an advisory signal
    # the operator scans, NOT a gate.
    rubric_block = q.get("rubric") if isinstance(q.get("rubric"), dict) else {}
    expected_tools = set(rubric_block.get("expected_tools") or [])
    called_tools = set(result.tools_called())

    # tool-call summary for the artifact
    tool_summary = [
        {
            "tool": tc.name,
            "arguments_keys": sorted(tc.arguments.keys()) if isinstance(tc.arguments, dict) else [],
        }
        for tc in result.tool_calls
    ]

    # tool_results: status + item_count rollup
    tool_results_summary = [
        {"tool": tr.get("tool", ""), "status": tr.get("status", ""), "item_count": tr.get("item_count", 0)}
        for tr in result.tool_results
    ]

    # Advisory latency budget — read from the new ``budgets:`` block. None
    # when the question doesn't declare a budget (no flag).
    budgets_block = q.get("budgets") if isinstance(q.get("budgets"), dict) else {}
    raw_budget = budgets_block.get("max_latency_s")
    try:
        expected_max_latency = float(raw_budget) if raw_budget is not None else None
    except (TypeError, ValueError):
        expected_max_latency = None

    return {
        "is_empty": not answer.strip(),
        "is_refusal": is_refusal(answer),
        "word_count": len(words),
        "char_count": len(answer),
        # NOTE: ``answer_meets_min_words`` was removed in PLAN-0099-W4 — the
        # word-count gate produced false WARNs on correctly-concise factual
        # answers and the v2.0 judge replaced it with the LENGTH-AGNOSTIC
        # ``framing`` dimension.
        "latency_within_budget": (result.latency_s <= expected_max_latency) if expected_max_latency else None,
        "ttft_s": None if (result.ttft_s != result.ttft_s) else round(result.ttft_s, 3),  # NaN-safe
        "latency_s": round(result.latency_s, 3),
        "phase_timings_ms": result.phase_timings_ms,
        "output_tokens": result.output_tokens,
        "tool_calls_summary": tool_summary,
        "tool_results_summary": tool_results_summary,
        "tool_call_count": len(result.tool_calls),
        "tool_result_count": len(result.tool_results),
        "distinct_tools_called": sorted(called_tools),
        "expected_tools": sorted(expected_tools),
        "tool_overlap_with_expected": sorted(called_tools & expected_tools),
        "missing_expected_tools": sorted(expected_tools - called_tools),
        # NOTE: ``entities_mentioned`` / ``entities_missing`` /
        # ``must_not_say_hits`` were removed in PLAN-0099-W4 — substring
        # matching of entity names / forbidden phrases was the source of
        # false WARNs (e.g. "missing NVDA" when the answer said "NVIDIA").
        # The v2.0 judge handles these checks semantically via rubric
        # ``required_facts`` / ``forbidden_facts``.
        "citation_count": len(result.citations),
        "contradiction_count": len(result.contradictions),
        "error": result.error,
        "status_code": result.status_code,
    }


def derive_pass_fail(heur: dict[str, Any]) -> tuple[str, list[str]]:
    """Reduce heuristics to a coarse PASS/WARN/FAIL bucket + reason list.

    Purely descriptive — not used for exit code. The aggregate banner uses
    this so the human reader sees a quick "how did it do?" without reading
    every JSON file.
    """
    reasons: list[str] = []
    bucket = "PASS"

    if heur["status_code"] != 200 or heur["error"]:
        reasons.append(f"http_status={heur['status_code']} error={heur['error']}")
        return "FAIL", reasons
    if heur["is_empty"]:
        reasons.append("empty_answer")
        return "FAIL", reasons
    # PLAN-0099-W4: removed ``must_not_say_hits``, ``entities_missing``, and
    # ``answer_meets_min_words`` from the bucket logic — the underlying
    # heuristic fields were dropped because they generated false WARNs and
    # the v2.0 judge handles these checks semantically (via rubric
    # required_facts / forbidden_facts + the LENGTH-AGNOSTIC framing
    # dimension). What remains here are the still-meaningful infrastructure
    # signals (empty answer, refusal classifier, latency-budget breach,
    # zero-tools-called).
    if heur["is_refusal"]:
        reasons.append("answer_classified_as_refusal")
        # refusal might be CORRECT (e.g. agg_a10 false-premise); leave at WARN
        # and let the human reader (or the LLM judge) make the final call.
        if bucket != "FAIL":
            bucket = "WARN"
    if heur["latency_within_budget"] is False:
        reasons.append(f"slow latency_s={heur['latency_s']}")
        if bucket == "PASS":
            bucket = "WARN"
    if heur["missing_expected_tools"] and not heur["distinct_tools_called"]:
        reasons.append(f"no_tools_called expected={heur['missing_expected_tools']}")
        if bucket == "PASS":
            bucket = "WARN"
    return bucket, reasons


# --------------------------------------------------------------------------
# Per-question persistence
# --------------------------------------------------------------------------


def _safe_slot(q_id: str, attempt_idx: int, max_attempts: int) -> str:
    """Filename slot — append ``_runN`` when --max-runs-per-q > 1."""
    base = "".join(c if c.isalnum() or c in "._-" else "_" for c in q_id)
    if max_attempts <= 1:
        return f"q_{base}"
    return f"q_{base}_run{attempt_idx + 1}"


def write_question_artifacts(
    *,
    out_dir: Path,
    slot: str,
    q: dict[str, Any],
    result: ChatRunResult,
    heur: dict[str, Any],
    bucket: str,
    reasons: list[str],
    judge_result: dict[str, Any] | None = None,
    trajectory_result: dict[str, Any] | None = None,  # --- W2 trajectory layer ---
) -> None:
    """Write q_<id>.json + q_<id>.log to the run directory.

    ``judge_result`` (PLAN-0104 W33) is the LLM-judge verdict for this Q. When
    present it is stored under the ``judge`` key alongside the legacy
    ``heuristics`` / ``bucket`` fields — both are kept so consumers can
    compare quality-based grading against the prior word-count heuristic
    during the rollout.
    """
    json_path = out_dir / f"{slot}.json"
    log_path = out_dir / f"{slot}.log"

    # v2 schema (PLAN-0099-W4): legacy top-level expected_* fields were
    # collapsed into rubric.* / budgets.* — we serialise from the new
    # locations so the artefact accurately reflects what the judge saw.
    rubric_block = q.get("rubric") if isinstance(q.get("rubric"), dict) else {}
    budgets_block = q.get("budgets") if isinstance(q.get("budgets"), dict) else {}
    payload = {
        "id": q.get("id"),
        "prompt": q.get("prompt"),
        "category": q.get("category"),
        "tags": q.get("tags") or [],
        "expected": {
            # ``expected.tools`` was a top-level hint; now sourced from rubric.
            "tools": list(rubric_block.get("expected_tools") or []),
            "max_latency_s": budgets_block.get("max_latency_s"),
        },
        # Legacy heuristic verdict — kept for backward compat (PLAN-0104 W33).
        "bucket": bucket,
        "reasons": reasons,
        "heuristics": heur,
        # New LLM-judge rubric verdict (PLAN-0104 W33). None when judge skipped.
        "rubric": Rubric.from_question(q).to_dict(),
        "judge": judge_result,
        # --- W2 trajectory layer ---
        # The tool-chain trajectory verdict (W2). None when trajectory grading is
        # off. Stored as a SEPARATE block — it is purely additive and never feeds
        # the answer ``judge`` verdict above.
        "trajectory": trajectory_result,
        "result": result.to_json_dict(),
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    # Human-readable log — one line per event, with relative receive time.
    lines: list[str] = []
    lines.append(f"# id={q.get('id')} prompt={q.get('prompt')!r}")
    lines.append(f"# bucket={bucket} reasons={reasons}")
    lines.append(f"# latency_s={result.latency_s:.3f} ttft_s={result.ttft_s} status={result.status_code}")
    lines.append("")
    timings_by_idx = {i: t_us for i, (_, t_us) in enumerate(result.event_timings)}
    for i, ev in enumerate(result.raw_events):
        t_us = timings_by_idx.get(i, 0)
        t_ms = t_us / 1000.0
        kind = ev.get("event", "?")
        data = ev.get("data")
        if isinstance(data, dict | list):
            preview = json.dumps(data)[:400]
        else:
            preview = str(data)[:400]
        lines.append(f"[{t_ms:>9.2f} ms] {kind:<18} {preview}")
    lines.append("")
    lines.append("# --- final answer ---")
    lines.append(result.answer_text or "<empty>")
    log_path.write_text("\n".join(lines))


def write_error_file(out_dir: Path, slot: str, exc: BaseException) -> None:
    """Persist a full traceback so failures are diagnosable post-mortem."""
    err_path = out_dir / f"{slot}.error.txt"
    err_path.write_text("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))


# --------------------------------------------------------------------------
# Human-readable Markdown report (PLAN-0099 W4)
# --------------------------------------------------------------------------
#
# Existing per-Q JSON artefacts are great for tooling but require dot-walking
# through several levels of nesting to read by hand. The Markdown report below
# gives the operator a single file with prompt → answer → tools → judge
# feedback per question, plus a cross-question variance table — so a session
# can be reviewed in one pass without opening 15 JSON files.
#
# The renderer is intentionally a pure function: it takes already-loaded dicts
# and returns a string. That keeps it trivially testable and means the runner
# can call it after every run without any file-system side effects beyond the
# final ``_report.md`` write.

_ANSWER_MAX_CHARS = 1500

# ``_judge_summary.json`` schema version. Bumped to "2.0" (audit 2026-06-11
# F9) to match the v2.0 CHAT_QUALITY_JUDGE prompt + the new hardening fields
# (``veto_counts``, ``grounding_veto_floor``, per-record ``veto`` blocks). The
# previous value (1) skewed below the judge prompt version and implied a v1
# schema that no longer exists.
_JUDGE_SUMMARY_SCHEMA_VERSION = "2.0"


def _fmt_duration(seconds: float) -> str:
    """Format ``seconds`` as ``Xm Ys`` (or ``Ys`` if under a minute)."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s"


def _parse_iso(ts: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp; return None if the field is missing/garbled."""
    if not ts:
        return None
    try:
        # ``datetime.fromisoformat`` handles the ``+00:00`` suffix we write.
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def _truncate_answer(text: str, q_id: str) -> str:
    """Truncate answer to ``_ANSWER_MAX_CHARS`` with an explicit pointer.

    Long answers blow up the markdown report — 1500 chars is enough to judge
    quality at a glance while keeping the file scannable. The pointer to the
    full JSON keeps the artefact discoverable.
    """
    if not text:
        return "*(empty answer)*"
    if len(text) <= _ANSWER_MAX_CHARS:
        return text
    return text[:_ANSWER_MAX_CHARS] + f"\n\n*[truncated, see q_{q_id}.json for full]*"


def _dim_field(dim_payload: dict[str, Any], *names: str) -> str:
    """Return the first non-empty string field — back-compat across judge schema versions.

    v2.0 uses ``feedback`` (per-dim) and ``reviewer_summary`` (top-level); v1.x
    used ``reason`` / ``notes``. We fall back gracefully so old artefacts still
    render rather than throwing KeyError.
    """
    for n in names:
        v = dim_payload.get(n)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def _group_by_question(artifacts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Bucket per-run artefacts by question id; preserves load order within a bucket."""
    by_q: dict[str, list[dict[str, Any]]] = {}
    for art in artifacts:
        q_id = art.get("id") or "unknown"
        by_q.setdefault(q_id, []).append(art)
    return by_q


def _safe_stdev(values: list[float]) -> float:
    """statistics.stdev requires N>=2; return 0.0 otherwise so the column always renders."""
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values)


def _render_run_block(art: dict[str, Any], run_idx: int) -> list[str]:
    """Render a single Run section inside a per-question block.

    Layout (three clearly-labelled sections):
      1. Run header line with verdict / score / latency
      2. LLM Answer — tools called, then the answer text
      3. Judge Evaluation — dimension table + reviewer summary
    """
    result = art.get("result") or {}
    heur = art.get("heuristics") or {}
    judge = art.get("judge") or {}
    q_id = art.get("id") or "unknown"
    bucket = art.get("bucket") or "?"
    latency = float(result.get("latency_s") or heur.get("latency_s") or 0.0)
    words = int(heur.get("word_count") or 0)
    answer_text = str(result.get("answer_text") or "")
    tool_calls = result.get("tool_calls") or []
    tools_called = sorted({(tc.get("name") or "") for tc in tool_calls if isinstance(tc, dict)})

    # ── Run header ──────────────────────────────────────────────────────────
    if judge:
        verdict = judge.get("verdict") or "?"
        score = judge.get("score")
        badge = "✅" if verdict == "PASS" else ("⚠️" if verdict == "WARN" else "❌")
        header = f"#### Run {run_idx} — {badge} {verdict} · {score}/100 · {latency:.1f}s · {words} words"
    else:
        header = f"#### Run {run_idx} — {bucket} · {latency:.1f}s · {words} words"

    lines: list[str] = [header, ""]

    # ── Section 1: LLM Answer ───────────────────────────────────────────────
    lines.append("**🤖 LLM Answer**")
    lines.append("")
    if tools_called:
        tools_str = ", ".join(f"`{t}`" for t in tools_called)
        lines.append(f"*Tools called ({len(tools_called)}):* {tools_str}")
    else:
        lines.append("*Tools called:* *(none)*")
    lines.append("")
    # Answer text in blockquote; truncate very long responses.
    truncated = _truncate_answer(answer_text, q_id)
    for line in truncated.splitlines() or [""]:
        lines.append(f"> {line}")
    lines.append("")

    # ── Section 2: Judge Evaluation ─────────────────────────────────────────
    if judge:
        v = judge.get("verdict") or "?"
        s = judge.get("score")
        lines.append(f"**⚖️ Judge Evaluation — {v} ({s}/100)**")
        lines.append("")
        dims = judge.get("dimensions") or {}
        if dims:
            # Dimension scores as a table for easy scanning.
            lines.append("| Dimension | Score | Feedback |")
            lines.append("|-----------|------:|---------|")
            for k, payload in dims.items():
                if not isinstance(payload, dict):
                    continue
                d_score = payload.get("score", "?")
                d_feedback = _dim_field(payload, "feedback", "reason") or ""
                lines.append(f"| {k} | {d_score}/25 | {d_feedback} |")
            lines.append("")
        # v2.0 reviewer_summary lives at the judge top level; v1.x used ``notes``.
        reviewer_summary = _dim_field(judge, "reviewer_summary", "notes")
        if reviewer_summary:
            lines.append(f"**Reviewer:** {reviewer_summary}")
            lines.append("")
        # Surface latency budget miss if present.
        if not heur.get("latency_within_budget", True):
            budget = (art.get("rubric") or {}).get("budgets", {}).get("max_latency_s") or (
                art.get("expected") or {}
            ).get("max_latency_s")
            lines.append(f"> ⏱ Latency budget exceeded — {latency:.1f}s vs {budget}s limit")
            lines.append("")
    else:
        # No judge — surface the heuristic reasons so the run is still informative.
        reasons = art.get("reasons") or []
        lines.append("**⚖️ Judge Evaluation**")
        lines.append("")
        lines.append("*(judge not run for this benchmark execution)*")
        if reasons:
            lines.append("")
            lines.append(f"**Heuristic reasons:** {'; '.join(reasons)}")
        lines.append("")

    return lines


def _render_question_block(q_id: str, artifacts: list[dict[str, Any]]) -> list[str]:
    """Render the per-question section with all its runs.

    Layout:
      1. Question header (ID, category, tags)
      2. Question text in blockquote
      3. Rubric summary (expected depth, tools, required/forbidden facts)
      4. Run-level stats summary
      5. One _render_run_block per run
    """
    first = artifacts[0]
    category = first.get("category") or "uncategorized"
    tags = first.get("tags") or []
    prompt = first.get("prompt") or "(no prompt recorded)"
    rubric = first.get("rubric") or {}

    # Aggregate stats across runs.
    judge_scores = [
        a["judge"].get("score")
        for a in artifacts
        if isinstance(a.get("judge"), dict) and isinstance(a["judge"].get("score"), int | float)
    ]
    verdicts = [a["judge"].get("verdict") for a in artifacts if isinstance(a.get("judge"), dict)]

    # ── Question header ──────────────────────────────────────────────────────
    tags_inline = f" `{'` `'.join(tags)}`" if tags else ""
    lines: list[str] = [f"### ❓ `{q_id}` — {category}{tags_inline}", ""]

    # ── Question text ────────────────────────────────────────────────────────
    lines.append("**Question asked:**")
    lines.append("")
    for line in prompt.splitlines():
        lines.append(f"> {line}")
    lines.append("")

    # ── Rubric summary ───────────────────────────────────────────────────────
    rubric_parts: list[str] = []
    if rubric.get("expected_depth"):
        rubric_parts.append(f"depth=`{rubric['expected_depth']}`")
    exp_tools = rubric.get("expected_tools") or (first.get("expected") or {}).get("tools") or []
    if exp_tools:
        rubric_parts.append(f"expected tools: {', '.join(f'`{t}`' for t in exp_tools)}")
    req_facts = rubric.get("required_facts") or []
    if req_facts:
        rubric_parts.append(f"must mention: {'; '.join(req_facts)}")
    forb_facts = rubric.get("forbidden_facts") or []
    if forb_facts:
        rubric_parts.append(f"must not say: {'; '.join(forb_facts)}")
    if rubric_parts:
        lines.append(f"**Rubric:** {' · '.join(rubric_parts)}")
        lines.append("")

    # ── Run stats ────────────────────────────────────────────────────────────
    n = len(artifacts)
    if judge_scores:
        mean = statistics.mean(judge_scores)
        sd = _safe_stdev([float(s) for s in judge_scores])
        verdict_badges = " ".join(("✅" if v == "PASS" else ("⚠️" if v == "WARN" else "❌")) for v in verdicts)
        lines.append(
            f"**{n} run{'s' if n != 1 else ''}** — mean score **{mean:.1f}/100** (σ={sd:.1f}) — {verdict_badges}"  # noqa: RUF001
        )
    else:
        buckets = [a.get("bucket") or "?" for a in artifacts]
        lines.append(f"**{n} run{'s' if n != 1 else ''}** — buckets: {' '.join(buckets)}")
    lines.append("")

    for i, art in enumerate(artifacts, start=1):
        lines.extend(_render_run_block(art, i))

    lines.append("---")
    lines.append("")
    return lines


def _render_variance_table(by_q: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Render the cross-question variance table."""
    lines: list[str] = ["## Cross-question variance", ""]
    lines.append("| Question | N | Mean | Stddev | Verdicts | Mean latency |")
    lines.append("|----------|---|------|--------|----------|--------------|")
    for q_id in sorted(by_q.keys()):
        arts = by_q[q_id]
        n = len(arts)
        scores = [
            a["judge"]["score"]
            for a in arts
            if isinstance(a.get("judge"), dict) and isinstance(a["judge"].get("score"), int | float)
        ]
        latencies = [
            float((a.get("result") or {}).get("latency_s") or (a.get("heuristics") or {}).get("latency_s") or 0.0)
            for a in arts
        ]
        if scores:
            mean = f"{statistics.mean(scores):.1f}"
            sd = f"{_safe_stdev([float(s) for s in scores]):.1f}"
        else:
            mean = "-"
            sd = "-"
        # Verdict roll-up: PASSx3 / WARNx1 etc.
        verdicts_counter: dict[str, int] = {}
        for a in arts:
            v = (a.get("judge") or {}).get("verdict") or a.get("bucket") or "?"
            verdicts_counter[v] = verdicts_counter.get(v, 0) + 1
        v_str = " ".join(f"{k}x{c}" for k, c in sorted(verdicts_counter.items()))
        mean_lat = f"{statistics.mean(latencies):.0f}s" if latencies else "-"
        lines.append(f"| {q_id} | {n} | {mean} | {sd} | {v_str} | {mean_lat} |")
    lines.append("")
    return lines


def _render_errors_section(artifacts: list[dict[str, Any]]) -> list[str]:
    """List any EXCEPTION / FAIL runs so they aren't buried."""
    bad = [a for a in artifacts if (a.get("bucket") == "EXCEPTION") or (a.get("result") or {}).get("error")]
    lines: list[str] = ["## Errors and exceptions", ""]
    if not bad:
        lines.append("*(none)*")
        lines.append("")
        return lines
    for a in bad:
        q_id = a.get("id") or "?"
        err = (a.get("result") or {}).get("error") or a.get("reasons")
        lines.append(f"- `{q_id}`: {err}")
    lines.append("")
    return lines


# --------------------------------------------------------------------------
# Failure-first headline (audit 2026-06-11 F5)
# --------------------------------------------------------------------------
#
# The original headline led with the average score + verdict counts + per-
# dimension averages — which AVERAGED AWAY the failures that matter (a single
# fabrication, a leaked stub, a latency breach). The redesign LEADS with the
# failures: min score, worst-N runs, fabrication list (grounding veto),
# degenerate-answer list, tool-failure list, and an aggregated latency-breach
# count. The rosy average is DEMOTED below.


def _run_score(art: dict[str, Any]) -> float | None:
    """Numeric judge score for a run, or None when not judged."""
    judge = art.get("judge")
    if isinstance(judge, dict) and isinstance(judge.get("score"), int | float):
        return float(judge["score"])
    return None


def _run_latency(art: dict[str, Any]) -> float:
    """Latency in seconds for a run (result first, heuristics fallback)."""
    return float((art.get("result") or {}).get("latency_s") or (art.get("heuristics") or {}).get("latency_s") or 0.0)


def _latency_breached(art: dict[str, Any]) -> bool:
    """True when this run breached its advisory latency budget."""
    # ``latency_within_budget`` is False only when a budget existed AND was
    # exceeded; None (no budget) and True (within budget) are both not breaches.
    return (art.get("heuristics") or {}).get("latency_within_budget") is False


def _veto_block(art: dict[str, Any]) -> dict[str, Any] | None:
    """Return the judge ``veto`` block for a run, if present."""
    judge = art.get("judge")
    if isinstance(judge, dict):
        veto = judge.get("veto")
        if isinstance(veto, dict):
            return veto
    return None


def _render_failure_first_headline(
    *,
    judge_summary: dict[str, Any] | None,
    artifacts: list[dict[str, Any]],
    worst_n: int = 5,
) -> list[str]:
    """Render the FAILURE-FIRST headline block (leads the report).

    Order (most actionable first):
      1. Worst (min) judge score + worst-N runs table.
      2. Fabrication list — runs vetoed for grounding < floor.
      3. Degenerate-answer list — runs hard-failed by the deterministic
         pre-check (leaked tokens / stub / empty / digit-drop).
      4. Tool-failure non-answer list.
      5. Aggregated latency-breach count.
    """
    lines: list[str] = ["## ⛔ Failures first", ""]

    judged = [a for a in artifacts if _run_score(a) is not None]
    scores = [s for a in artifacts if (s := _run_score(a)) is not None]

    # 1) Min score + worst-N --------------------------------------------------
    if scores:
        min_score = min(scores)
        lines.append(f"**Worst run score:** {min_score:.0f}/100 (the average HIDES this — see below).")
    else:
        lines.append("**Worst run score:** *(no judged runs)*")
    lines.append("")

    if judged:
        worst = sorted(judged, key=lambda a: _run_score(a) or 0.0)[:worst_n]
        lines.append(f"**Worst {min(worst_n, len(worst))} runs**")
        lines.append("")
        lines.append("| Run | Verdict | Score | Why |")
        lines.append("|-----|---------|------:|-----|")
        for a in worst:
            slot = a.get("slot") or a.get("id") or "?"
            judge = a.get("judge") or {}
            verdict = judge.get("verdict") or "?"
            score = judge.get("score")
            veto = _veto_block(a)
            why = (veto.get("detail") if veto else "") or (judge.get("reviewer_summary") or judge.get("notes") or "")
            why = str(why).replace("\n", " ")[:160] or "—"
            lines.append(f"| `{slot}` | {verdict} | {score}/100 | {why} |")
        lines.append("")

    # 2) Fabrication list (grounding veto) -----------------------------------
    fabrications = [a for a in artifacts if (v := _veto_block(a)) and v.get("type") == "grounding"]
    floor = (judge_summary or {}).get("grounding_veto_floor")
    floor_str = f" (grounding < {floor})" if floor is not None else ""
    lines.append(f"**🚨 Fabrication list — grounding veto{floor_str}:** {len(fabrications)}")
    lines.append("")
    if fabrications:
        for a in fabrications:
            slot = a.get("slot") or a.get("id") or "?"
            v = _veto_block(a) or {}
            lines.append(f"- `{slot}` — {v.get('detail') or 'grounding below floor'}")
        lines.append("")

    # 3) Degenerate-answer list ----------------------------------------------
    degenerates = [a for a in artifacts if (v := _veto_block(a)) and v.get("type") == "degenerate"]
    lines.append(f"**🧨 Degenerate-answer list (leaked tokens / stub / empty / digit-drop):** {len(degenerates)}")
    lines.append("")
    if degenerates:
        for a in degenerates:
            slot = a.get("slot") or a.get("id") or "?"
            v = _veto_block(a) or {}
            lines.append(f"- `{slot}` — {v.get('reason')}: {v.get('detail') or ''}".rstrip())
        lines.append("")

    # 4) Tool-failure non-answer list ----------------------------------------
    tool_fails = [a for a in artifacts if (v := _veto_block(a)) and v.get("type") == "tool_failure"]
    lines.append(f"**🔌 Tool-failure non-answer list:** {len(tool_fails)}")
    lines.append("")
    if tool_fails:
        for a in tool_fails:
            slot = a.get("slot") or a.get("id") or "?"
            v = _veto_block(a) or {}
            lines.append(f"- `{slot}` — {v.get('detail') or 'tool failure non-answer'}")
        lines.append("")

    # 5) Latency-breach count ------------------------------------------------
    breaches = [a for a in artifacts if _latency_breached(a)]
    lines.append(f"**⏱ Latency-budget breaches:** {len(breaches)} of {len(artifacts)} runs")
    if breaches:
        lines.append("")
        for a in breaches:
            slot = a.get("slot") or a.get("id") or "?"
            lines.append(f"- `{slot}` — {_run_latency(a):.1f}s")
    lines.append("")

    return lines


def _render_regression_section(
    *,
    artifacts: list[dict[str, Any]],
    baseline_artifacts: list[dict[str, Any]] | None,
    baseline_label: str | None,
) -> list[str]:
    """Render the regression section comparing this run vs a baseline (F6 gap).

    For each question id present in BOTH runs we show the per-question mean
    score delta and flag any verdict regression (PASS→WARN/FAIL or
    WARN→FAIL). A worsening delta or verdict regression is marked ⬇️.
    """
    lines: list[str] = ["## Regression vs baseline", ""]
    if not baseline_artifacts:
        lines.append("*(no baseline run found — pass --baseline <runs-dir> or place a prior run alongside this one.)*")
        lines.append("")
        return lines

    lines.append(f"**Baseline:** `{baseline_label or 'unknown'}`")
    lines.append("")

    # Worst verdict ranking so we can detect a regression direction.
    _RANK = {"PASS": 0, "WARN": 1, "FAIL": 2, "SKIPPED": 3, "ERROR": 4}

    def _by_q_mean(arts: list[dict[str, Any]]) -> dict[str, tuple[float | None, str]]:
        """question id -> (mean score or None, worst verdict)."""
        grouped = _group_by_question(arts)
        out: dict[str, tuple[float | None, str]] = {}
        for q_id, runs in grouped.items():
            scs = [s for r in runs if (s := _run_score(r)) is not None]
            mean = statistics.mean(scs) if scs else None
            worst_v = "PASS"
            for r in runs:
                v = (r.get("judge") or {}).get("verdict") or r.get("bucket") or "PASS"
                if _RANK.get(v, 0) > _RANK.get(worst_v, 0):
                    worst_v = v
            out[q_id] = (mean, worst_v)
        return out

    cur = _by_q_mean(artifacts)
    base = _by_q_mean(baseline_artifacts)
    shared = sorted(set(cur) & set(base))

    if not shared:
        lines.append("*(baseline shares no question ids with this run — nothing to compare.)*")
        lines.append("")
        return lines

    lines.append("| Question | Baseline | Current | Δ | Verdict (base→cur) |")
    lines.append("|----------|---------:|--------:|---:|--------------------|")
    regressions = 0
    for q_id in shared:
        b_mean, b_v = base[q_id]
        c_mean, c_v = cur[q_id]
        b_str = f"{b_mean:.1f}" if b_mean is not None else "-"
        c_str = f"{c_mean:.1f}" if c_mean is not None else "-"
        if b_mean is not None and c_mean is not None:
            delta = c_mean - b_mean
            delta_str = f"{delta:+.1f}"
        else:
            delta = 0.0
            delta_str = "-"
        verdict_regressed = _RANK.get(c_v, 0) > _RANK.get(b_v, 0)
        flag = " ⬇️" if (verdict_regressed or delta < 0) else ""
        if verdict_regressed or delta < 0:
            regressions += 1
        lines.append(f"| `{q_id}` | {b_str} | {c_str} | {delta_str} | {b_v} → {c_v}{flag} |")
    lines.append("")
    lines.append(f"**Regressions (lower score OR verdict downgrade):** {regressions} of {len(shared)} shared questions")
    lines.append("")
    return lines


# --------------------------------------------------------------------------
# PLAN-0110 W4 — durable trend store integration + store-backed regressions
# --------------------------------------------------------------------------
#
# The single ``--baseline`` diff above (audit 2026-06-11) compares this run vs
# ONE prior run directory on disk. W4 layers a DURABLE store on top: every run
# is appended to ``trend.sqlite`` (+ jsonl sidecar) and the run is diffed vs a
# *registered* baseline AND a rolling window pulled FROM the store — so a
# regression is caught even when the prior run directory has been deleted.


def _artifact_question_rows(per_question_artifacts: list[dict[str, Any]]) -> list[QuestionRow]:
    """Project each judged per-Q artefact into a typed ``QuestionRow``.

    We read from the structured ``verdict_decision`` block (PLAN-0110 W1) — the
    authoritative tiered verdict — never the legacy heuristic ``bucket``. A run
    that was not judged (``--judge`` absent, or judge SKIPPED) has no
    ``verdict_decision`` and is skipped here: the trend store only records graded
    verdicts, so a non-judge smoke run appends an empty (0-question) run row
    rather than polluting the series with un-graded placeholders.
    """
    rows: list[QuestionRow] = []
    for art in per_question_artifacts:
        judge = art.get("judge")
        if not isinstance(judge, dict):
            continue
        decision = judge.get("verdict_decision")
        if not isinstance(decision, dict):
            continue
        # ``verdict_decision.dimensions`` is the FLAT int form (4 keys, 0-25
        # each) — distinct from the top-level ``dimensions`` block which is the
        # nested {score,feedback,reason} judge output. We want the ints.
        dims = decision.get("dimensions") or {}
        gc = decision.get("grounding_check") or {}
        # The per-Q artefact carries a ``slot`` like ``q_<id>__r1``; the trend
        # store keys on (question_id, run_index). We derive run_index from the
        # slot suffix when present, else fall back to a stable 0.
        question_id = str(art.get("id") or art.get("slot") or "unknown")
        run_index = _slot_run_index(str(art.get("slot") or ""))
        rows.append(
            QuestionRow(
                question_id=question_id,
                run_index=run_index,
                verdict=str(decision.get("verdict") or "FAIL"),
                fail_reason=decision.get("fail_reason"),
                quality_score=int(decision.get("quality_score") or 0),
                dim_tool_use=int(dims.get("tool_use") or 0),
                dim_grounding=int(dims.get("grounding") or 0),
                dim_framing=int(dims.get("framing") or 0),
                # The judge dimension key is ``refusal_judgment``; the trend
                # column is ``dim_refusal``.
                dim_refusal=int(dims.get("refusal_judgment") or 0),
                grounding_contradicted=int(gc.get("contradicted") or 0),
                latency_breach=1 if _latency_breached(art) else 0,
            )
        )
    return rows


def _slot_run_index(slot: str) -> int:
    """Best-effort 0-based repeat index from a slot like ``q_foo__r2`` → 1.

    The runner names slots ``<id>__r<N>`` (1-based) when ``max_runs_per_q>1``
    and just ``<id>`` for a single run. We map ``r<N>`` → N-1 so the trend
    ``run_index`` is 0-based per PRD §6.4; anything unrecognised → 0.
    """
    marker = "__r"
    if marker in slot:
        tail = slot.rsplit(marker, 1)[1]
        if tail.isdigit():
            return max(int(tail) - 1, 0)
    return 0


def _build_run_row(
    *,
    run_ts: str,
    started_at: str,
    meta: dict[str, Any],
    question_rows: list[QuestionRow],
) -> RunRow:
    """Assemble the run-level ``RunRow`` summary from the per-Q rows + meta.

    Verdict counts + the mean additive quality_score are derived from the SAME
    rows that go into ``question_results`` so the run summary can never silently
    disagree with its detail (feedback_audit_returned_value_persistence).
    """
    counts = {"STRONG": 0, "PASS": 0, "WEAK": 0, "FAIL": 0}
    for qr in question_rows:
        counts[qr.verdict] = counts.get(qr.verdict, 0) + 1
    scores = [qr.quality_score for qr in question_rows]
    mean_score = round(sum(scores) / len(scores), 2) if scores else 0.0
    return RunRow(
        run_ts=run_ts,
        started_at=started_at,
        judge_prompt_version=str(meta.get("judge_prompt_version") or ""),
        judge_model_id=str(meta.get("judge_model_id") or ""),
        verdict_model_version=str(meta.get("verdict_model_version") or ""),
        n_questions=len(question_rows),
        n_pass=counts["PASS"],
        n_weak=counts["WEAK"],
        n_fail=counts["FAIL"],
        n_strong=counts["STRONG"],
        mean_quality_score=mean_score,
        is_baseline=0,
        questions=list(question_rows),
    )


def _compute_store_regressions(
    *,
    store: TrendStore,
    run_ts: str,
    current_rows: list[QuestionRow],
    window: int = 5,
) -> dict[str, Any]:
    """Diff the current run vs the registered baseline + a rolling window.

    Pulls the comparison rows FROM the store (not a run directory) so the diff
    survives run-dir cleanup. The rolling window is the single run immediately
    before this one (``window`` reserved for a future multi-run aggregate);
    using the prior run keeps the "did this commit regress vs last commit"
    signal sharp.
    """
    cur = [
        {
            "question_id": qr.question_id,
            "run_index": qr.run_index,
            "verdict": qr.verdict,
            "fail_reason": qr.fail_reason,
            "quality_score": qr.quality_score,
            "grounding_contradicted": qr.grounding_contradicted,
            "latency_breach": qr.latency_breach,
        }
        for qr in current_rows
    ]

    baseline_ts = store.get_baseline_run_ts()
    baseline_rows = store.get_question_rows(baseline_ts) if baseline_ts else None

    # Rolling window: the most recent prior run (excluding this run_ts).
    prior = store.recent_run_ts(limit=1, before=run_ts)
    window_ts = prior[0] if prior else None
    window_rows = store.get_question_rows(window_ts) if window_ts else None

    return detect_regressions(
        current_rows=cur,
        baseline_rows=baseline_rows,
        baseline_label=baseline_ts,
        window_rows=window_rows,
        window_label=window_ts,
    )


def _render_store_regression_section(regressions: dict[str, Any]) -> list[str]:
    """Render the W4 store-backed regression summary (a small, delimited block).

    Kept deliberately compact + self-contained so the W5 report rewrite can call
    it as-is for the top-of-report regression banner (FR-15) without untangling
    it from the failure-first section.
    """
    lines: list[str] = ["## 📉 Regressions (durable trend, machine: `_regressions.json`)", ""]
    total = int(regressions.get("total_regressions") or 0)
    if not regressions.get("has_regressions"):
        # Distinguish "compared, none found" from "nothing to compare against".
        base = regressions.get("baseline") or {}
        win = regressions.get("window") or {}
        if not base.get("available") and not (win and win.get("available")):
            lines.append("*(no prior run in the trend store — this is the first recorded run.)*")
        else:
            lines.append("**No regressions vs baseline or the prior run.** ✅")
        lines.append("")
        return lines

    lines.append(f"**{total} regression(s) detected** ⬇️")
    lines.append("")
    for which in ("baseline", "window"):
        block = regressions.get(which)
        if not block or not block.get("available"):
            continue
        regs = block.get("regressions") or []
        label = block.get("label") or "?"
        kind = "registered baseline" if which == "baseline" else "prior run"
        lines.append(f"**vs {kind}** `{label}` — {len(regs)} of {block.get('shared_questions', 0)} shared")
        lines.append("")
        if regs:
            lines.append("| Question | Verdict | Score Δ | Why |")
            lines.append("|----------|---------|--------:|-----|")
            for r in regs:
                qid = f"{r['question_id']}__r{int(r['run_index']) + 1}"
                verdict = f"{r['verdict_from']} → {r['verdict_to']}"
                why = "; ".join(r.get("reasons") or []) or "—"
                lines.append(f"| `{qid}` | {verdict} | {r['score_delta']:+d} | {why} |")
            lines.append("")
    return lines


# --------------------------------------------------------------------------
# PLAN-0110 W5 — single authoritative verdict headline + expanded failures
# --------------------------------------------------------------------------
#
# The report now prints EXACTLY ONE authoritative verdict system: the tiered
# ``verdict_decision`` (STRONG/PASS/WEAK/FAIL) produced by the judge. The legacy
# heuristic buckets (PASS/WARN/FAIL) and the soft average are DEMOTED into a
# collapsed ``<details>`` appendix clearly labelled "legacy / non-authoritative"
# (FR-18). FAIL always leads — the headline can never average a fabrication away.


# Authoritative verdict order: FAIL first (most actionable), then WEAK, PASS,
# STRONG. This is the DISPLAY order in the headline, independent of severity
# rank — we lead with the failures a reader must act on.
_VERDICT_DISPLAY_ORDER = ("FAIL", "WEAK", "PASS", "STRONG")


def _verdict_decision(art: dict[str, Any]) -> dict[str, Any] | None:
    """Return the tiered ``verdict_decision`` block for a run, if present.

    This is the AUTHORITATIVE tiered verdict (PLAN-0110 W1). A run that was not
    judged (``--judge`` absent / judge SKIPPED) has no ``verdict_decision`` and
    is excluded from the authoritative headline counts.
    """
    judge = art.get("judge")
    if isinstance(judge, dict):
        decision = judge.get("verdict_decision")
        if isinstance(decision, dict):
            return decision
    return None


def _render_authoritative_verdict_headline(artifacts: list[dict[str, Any]]) -> list[str]:
    """Render the SINGLE authoritative tiered-verdict count line (FAIL-first).

    This is the one verdict system a reader is shown in the headline (FR-18).
    Counts are drawn from the tiered ``verdict_decision`` only — never the
    legacy heuristic bucket. When no run carries a tiered verdict (a non-judge
    smoke run) we say so explicitly rather than printing a misleading zero line.
    """
    lines: list[str] = ["## ⛔ Verdict (authoritative)", ""]
    decided = [d for a in artifacts if (d := _verdict_decision(a)) is not None]
    if not decided:
        lines.append("*(no tiered verdicts — run with `--judge` to grade. The")
        lines.append("legacy heuristic buckets in the appendix are advisory only.)*")
        lines.append("")
        return lines

    counts: dict[str, int] = {}
    for d in decided:
        v = str(d.get("verdict") or "FAIL")
        counts[v] = counts.get(v, 0) + 1
    # FAIL leads, always — order by the fixed display order, then any unknowns.
    ordered = [v for v in _VERDICT_DISPLAY_ORDER if counts.get(v)]
    ordered += [v for v in sorted(counts) if v not in _VERDICT_DISPLAY_ORDER and counts[v]]
    summary = " · ".join(f"{counts[v]} {v}" for v in ordered) or "(none)"
    lines.append(f"**{summary}**  ← tiered verdict, FAIL first (the single authority).")
    lines.append("")
    return lines


def _excerpt(text: str, *, limit: int = 160) -> str:
    """One-line, length-capped excerpt of an answer for the failures section."""
    flat = " ".join((text or "").split())
    return (flat[:limit] + " …") if len(flat) > limit else (flat or "—")


def _render_tiered_failures(artifacts: list[dict[str, Any]]) -> list[str]:
    """Render every tiered FAIL, expanded so it is impossible to miss (FR-17).

    For each run whose tiered verdict is FAIL we print:
      * the slot + triggering ``InvariantCode`` (``fail_reason``);
      * a one-line excerpt of the offending answer; and
      * for ``GROUNDING_CONTRADICTED`` the claim-vs-sample mismatch inline
        (claim value, nearest sampled value, delta) drawn from the
        ``grounding_check.examples`` the W3 numeric cross-check populated.

    A FAIL with no ``fail_reason`` (a sub-60 soft-score band FAIL, not a fired
    gate) is still listed with its quality_score so a reader sees WHY it failed.
    """
    lines: list[str] = ["## ⛔ Failures (every FAIL — expanded)", ""]
    fails = [(a, d) for a in artifacts if (d := _verdict_decision(a)) is not None and str(d.get("verdict")) == "FAIL"]
    if not fails:
        lines.append("**No tiered FAILs.** ✅")
        lines.append("")
        return lines

    for art, decision in fails:
        slot = art.get("slot") or art.get("id") or "?"
        fail_reason = decision.get("fail_reason")
        score = decision.get("quality_score")
        if fail_reason:
            lines.append(f"- `{slot}` — **FAIL[{fail_reason}]**")
        else:
            # Soft-band FAIL: no gate fired, the quality_score itself is < 60.
            lines.append(f"- `{slot}` — **FAIL** (quality_score {score}/100 < 60 — soft-band fail)")
        answer = ((art.get("result") or {}).get("answer_text")) or ""
        lines.append(f'    answer excerpt: "{_excerpt(answer)}"')
        # GROUNDING_CONTRADICTED — surface the claim↔sample mismatch inline so
        # the contradiction is never hidden behind an averaged grounding score.
        if fail_reason == "GROUNDING_CONTRADICTED":
            examples = ((decision.get("grounding_check") or {}).get("examples")) or []
            for ex in examples:
                field_name = ex.get("field") or "?"
                claim_text = ex.get("claim_text") or ex.get("claim")
                nearest = ex.get("nearest_sample")
                delta = ex.get("delta")
                delta_str = f" (Δ {delta:g})" if isinstance(delta, int | float) else ""
                lines.append(f"    claim `{claim_text}` vs sampled `{field_name}`={nearest}{delta_str}")
    lines.append("")
    return lines


# --- W2 trajectory layer ---
def _render_trajectory_section(judge_summary: dict[str, Any] | None) -> list[str]:
    """Render the "Trajectory (MUST-2)" report section from the W2 roll-up.

    Reads the ``trajectory`` block on ``judge_summary`` (added by the runner when
    trajectory grading is on). Surfaces the headline MUST-2 metrics — mean
    trajectory score + the two deterministic pre-signal totals (redundant turns,
    unrecovered failures) — plus the per-dimension averages. Returns an empty
    list when there is no trajectory block (grading was off / offline), so the
    report is byte-identical to a no-trajectory run in that case.
    """
    traj = (judge_summary or {}).get("trajectory")
    if not isinstance(traj, dict):
        return []
    lines: list[str] = []
    lines.append("## Trajectory (MUST-2)")
    lines.append("")
    lines.append(
        "> The agent's TOOL-CHAIN PROCESS, graded separately from the answer "
        "(it does NOT change the answer verdict). `redundant`/`unrecovered` are "
        "deterministic LLM-free pre-signals."
    )
    lines.append("")
    mean_score = traj.get("mean_score")
    mean_str = f"{mean_score:.2f} / 100" if isinstance(mean_score, int | float) else "-"
    redundant = int(traj.get("redundant_turns_n") or 0)
    unrecovered = int(traj.get("unrecovered_turns_n") or 0)
    n_graded = traj.get("n_graded")
    n_records = traj.get("n_records")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Mean trajectory score | {mean_str} |")
    lines.append(f"| Redundant turns (identical re-calls) | {redundant} |")
    lines.append(f"| Unrecovered failures (gave up / looped) | {unrecovered} |")
    lines.append(f"| Graded / total | {n_graded} / {n_records} |")
    dim_avg = traj.get("dimension_avg") or {}

    def _fmt_dim(v: Any) -> str:
        return f"{v:.1f}" if isinstance(v, int | float) else "-"

    dims_str = " · ".join(f"{k} {_fmt_dim(v)}" for k, v in dim_avg.items()) or "(none)"
    lines.append(f"| Dimensions (avg) | {dims_str} |")
    lines.append("")
    return lines


def _render_report_md(
    *,
    meta: dict[str, Any],
    summary: dict[str, Any],
    judge_summary: dict[str, Any] | None,
    per_question_artifacts: list[dict[str, Any]],
    baseline_artifacts: list[dict[str, Any]] | None = None,
    baseline_label: str | None = None,
    store_regressions: dict[str, Any] | None = None,
) -> str:
    """Render a human-readable Markdown report for a benchmark run.

    Inputs are the in-memory dicts already produced by the runner — no I/O.
    ``per_question_artifacts`` is the list of ``q_<id>[_runN].json`` payloads
    (the runner passes them directly to avoid re-reading from disk).

    Section order (FAILURE-FIRST + SINGLE-AUTHORITY, PLAN-0110 W5 / §6.6.1):
      1. Run header (timing, base URL, judge model, filters)
      2. ⛔ Verdict (authoritative) — the ONE tiered verdict count line, FAIL
         first (FR-18); the legacy buckets are removed from the headline.
      3. 📉 Regressions (durable trend) — surfaced AT THE TOP (FR-15), with a
         link to the machine-readable ``_regressions.json``.
      4. ⛔ Failures (every tiered FAIL — expanded): each FAIL with its
         triggering ``InvariantCode``, an answer excerpt, and for
         ``GROUNDING_CONTRADICTED`` the claim-vs-sample mismatch inline (FR-17).
      5. ⛔ Failures first (legacy veto headline — worst-N / fabrication /
         degenerate / tool-failure / latency-breach lists), kept for detail.
      6. Regression vs baseline (single-baseline disk diff, when available).
      7. <details> Soft-score appendix — the average + per-dimension means +
         the legacy heuristic buckets, DEMOTED + collapsed + labelled
         non-authoritative (FR-16/FR-18).
      8. Per-question detail + variance table + Errors section.

    ``store_regressions`` is the W4 durable-trend regression block (FR-15); when
    None the top-of-report regression banner is omitted (the runner always
    passes it). Supports both v2.0 judge schema (``feedback`` /
    ``reviewer_summary``) and v1.x (``reason`` / ``notes``) — falls back
    gracefully so old artefacts still render. ``baseline_artifacts`` is
    optional; when None the single-baseline section renders a "no baseline" note.
    """
    started = _parse_iso(meta.get("started_at"))
    ended = _parse_iso(meta.get("ended_at"))
    duration_s = (ended - started).total_seconds() if (started and ended) else 0.0
    out_dir_label = meta.get("out_dir_label") or "run"
    base_url = meta.get("base_url") or "?"
    tags = meta.get("tags_filter")
    tags_str = ", ".join(tags) if tags else "*(none)*"
    n_questions = meta.get("total_questions") or 0
    n_runs = meta.get("total_runs") or 0
    max_runs = meta.get("max_runs_per_q") or 1

    lines: list[str] = []
    lines.append(f"# Chat Quality Benchmark — {out_dir_label}")
    lines.append("")

    # --- Header block ---------------------------------------------------
    started_str = started.strftime("%Y-%m-%d %H:%M:%S UTC") if started else "(unknown)"
    ended_str = ended.strftime("%Y-%m-%d %H:%M:%S UTC") if ended else "(unknown)"
    lines.append(f"**Started:** {started_str}")
    lines.append(f"**Ended:** {ended_str} ({_fmt_duration(duration_s)})")
    lines.append(f"**Base URL:** {base_url}")
    lines.append(f"**Tags filter:** {tags_str}")
    lines.append(f"**Questions:** {n_questions} (x {max_runs} runs each = {n_runs} total)")
    if judge_summary:
        judge_model = judge_summary.get("model") or meta.get("judge_model") or "(default)"
        lines.append(f"**Judge:** {judge_model}")
    lines.append("")

    # --- AUTHORITATIVE VERDICT (the single headline) -------------------
    # Exactly ONE verdict system in the headline (FR-18): the tiered verdict,
    # FAIL first. The legacy heuristic buckets are NOT printed here — they live
    # only in the collapsed soft-score appendix below, labelled non-authoritative.
    lines.extend(_render_authoritative_verdict_headline(per_question_artifacts))

    # --- Regressions AT THE TOP (FR-15) --------------------------------
    # The durable-trend regression delta (downgrades, score drops, new
    # invariants) is surfaced above any average + a link to the machine-readable
    # ``_regressions.json`` is printed. When the runner did not compute a store
    # diff (store_regressions=None) the banner is omitted.
    if store_regressions is not None:
        lines.extend(_render_store_regression_section(store_regressions))

    # --- EXPANDED FAILURES (FR-17) -------------------------------------
    # Every tiered FAIL, with its triggering invariant + answer excerpt +
    # (for GROUNDING_CONTRADICTED) the claim-vs-sample mismatch inline.
    lines.extend(_render_tiered_failures(per_question_artifacts))

    # --- Legacy veto failure-first headline (detail) -------------------
    # Kept for the worst-N / fabrication / degenerate / tool-failure / latency
    # detail it provides; it is NO LONGER the headline (the tiered verdict above
    # is). The average is intentionally NOT in this block.
    lines.extend(
        _render_failure_first_headline(
            judge_summary=judge_summary,
            artifacts=per_question_artifacts,
        )
    )

    # --- W2 trajectory layer ---
    # The "Trajectory (MUST-2)" section: mean trajectory score + the two
    # deterministic pre-signal totals + per-dimension averages. Empty (no-op)
    # when the run had no trajectory block, so a no-trajectory report is
    # unchanged.
    lines.extend(_render_trajectory_section(judge_summary))

    # --- Regression vs baseline (single-baseline disk diff) ------------
    lines.extend(
        _render_regression_section(
            artifacts=per_question_artifacts,
            baseline_artifacts=baseline_artifacts,
            baseline_label=baseline_label,
        )
    )

    # --- Soft-score appendix (DEMOTED + COLLAPSED) ---------------------
    # FR-16: the average + per-dimension means + the legacy heuristic buckets are
    # the SECONDARY, smooth-over-failures view. They are collapsed inside a
    # <details> block and clearly labelled non-authoritative so a reader is never
    # shown two disagreeing scores at the same altitude (FR-18).
    lines.append("<details>")
    lines.append(
        "<summary>Soft-score appendix (means, per-dimension averages, legacy buckets — non-authoritative)</summary>"
    )
    lines.append("")
    lines.append("> These numbers smooth over the failures above and MUST NOT be")
    lines.append("> read as the headline. The tiered **Verdict (authoritative)** at")
    lines.append("> the top is the grade; the legacy heuristic buckets here are an")
    lines.append("> advisory second opinion kept for the rollout — do not gate on them.")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    if judge_summary:
        score_avg = judge_summary.get("score_avg")
        score_avg_str = f"{score_avg:.2f} / 100" if isinstance(score_avg, int | float) else "-"
        lines.append(f"| Judge avg score (smooths failures) | {score_avg_str} |")
        score_min = judge_summary.get("score_min")
        score_min_str = f"{score_min} / 100" if isinstance(score_min, int | float) else "-"
        lines.append(f"| Judge min score | {score_min_str} |")
        veto_counts = judge_summary.get("veto_counts") or {}
        if any(veto_counts.values()):
            veto_str = " · ".join(f"{c} {v}" for v, c in veto_counts.items() if c)
            lines.append(f"| Vetoes / hard-fails | {veto_str} |")
        dim_avg = judge_summary.get("dimension_avg") or {}

        def _fmt_dim(v: Any) -> str:
            return f"{v:.1f}" if isinstance(v, int | float) else "-"

        dims_str = " · ".join(f"{k} {_fmt_dim(v)}" for k, v in dim_avg.items()) or "(none)"
        lines.append(f"| Dimensions (avg) | {dims_str} |")
    bucket_counts = (summary or {}).get("bucket_counts") or {}
    bucket_str = " · ".join(f"{c} {v}" for v, c in bucket_counts.items() if c) or "(none)"
    lines.append(f"| Heuristic buckets (legacy — ADVISORY ONLY, not authoritative) | {bucket_str} |")
    lines.append("")
    lines.append("</details>")
    lines.append("")

    # --- Per-question detail -------------------------------------------
    lines.append("## Per-question detail")
    lines.append("")
    if not per_question_artifacts:
        lines.append("*(no runs to report — the benchmark produced zero per-question artefacts.)*")
        lines.append("")
    else:
        by_q = _group_by_question(per_question_artifacts)
        for q_id in sorted(by_q.keys()):
            lines.extend(_render_question_block(q_id, by_q[q_id]))

        # --- Variance table --------------------------------------------
        lines.extend(_render_variance_table(by_q))

    # --- Errors -------------------------------------------------------
    lines.extend(_render_errors_section(per_question_artifacts))

    return "\n".join(lines)


# --------------------------------------------------------------------------
# Baseline / regression support (audit 2026-06-11 — missing piece)
# --------------------------------------------------------------------------


def _load_run_artifacts(run_dir: Path) -> list[dict[str, Any]]:
    """Load all ``q_*.json`` artefacts from a run directory (sorted, lenient)."""
    arts: list[dict[str, Any]] = []
    for q_file in sorted(run_dir.glob("q_*.json")):
        try:
            arts.append(json.loads(q_file.read_text()))
        except json.JSONDecodeError:
            continue
    return arts


def _autopick_baseline(out_parent: Path, current_run_dir: Path) -> Path | None:
    """Pick the most recent PRIOR ``run_*`` dir under ``out_parent``.

    Used when ``--baseline`` is not given. We sort the sibling ``run_*``
    directories by name (the timestamps sort lexicographically) and return the
    newest one that is NOT the current run and that actually contains judged
    artefacts. Returns None when there is no usable prior run.
    """
    if not out_parent.is_dir():
        return None
    candidates = sorted(
        (d for d in out_parent.glob("run_*") if d.is_dir() and d.resolve() != current_run_dir.resolve()),
        reverse=True,
    )
    for d in candidates:
        if any(d.glob("q_*.json")):
            return d
    return None


class _StandaloneClient(RagChatClient):
    """Same client, but raises instead of calling pytest.skip on errors.

    The harness was authored for pytest, so its failure paths call
    ``pytest.skip``. In a standalone script that's the wrong behavior —
    we want exceptions to bubble so the per-question artifact can capture
    the traceback. This subclass overrides the two skip-points with raises.
    """

    def login(self) -> str:
        if self._access_token is not None:
            return self._access_token
        import httpx

        try:
            resp = self._client.post("/v1/auth/dev-login")
        except httpx.RequestError as exc:
            raise RuntimeError(f"dev-login network error: {exc}") from exc
        if resp.status_code != 200:
            raise RuntimeError(
                f"dev-login failed status={resp.status_code} body={resp.text[:300]!r}",
            )
        body = resp.json()
        token = body.get("access_token")
        if not isinstance(token, str):
            raise RuntimeError(f"dev-login returned no access_token: {body!r}")
        self._access_token = token
        return token

    def ask(self, question: str, *, entity_ids: list[str] | None = None) -> ChatRunResult:
        import httpx

        token = self.login()
        payload = {
            "message": question,
            "entity_ids": entity_ids or [],
            # Always fresh thread_id (BP-completion-cache key collision).
            "thread_id": str(uuid4()),
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        start = time.monotonic()
        for attempt in range(2):
            try:
                with self._client.stream("POST", "/v1/chat/stream", json=payload, headers=headers) as resp:
                    status = resp.status_code
                    if status == 401 and attempt == 0:
                        self._access_token = None
                        token = self.login()
                        headers["Authorization"] = f"Bearer {token}"
                        continue
                    if status != 200:
                        body_preview = b""
                        try:
                            body_preview = resp.read()[:500]
                        except Exception:  # noqa: S110 — diagnostic-only
                            pass
                        return ChatRunResult(
                            question=question,
                            status_code=status,
                            latency_s=time.monotonic() - start,
                            answer_text="",
                            error={"code": "HTTP_ERROR", "message": body_preview.decode(errors="replace")},
                        )
                    events, timings = _read_sse_events(resp, start)
                    return _events_to_result(
                        question,
                        status,
                        events,
                        time.monotonic() - start,
                        timings,
                    )
            except httpx.RequestError as exc:
                raise RuntimeError(f"chat stream network error: {exc}") from exc
        raise RuntimeError("unreachable")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Chat-endpoint quality benchmark runner.")
    p.add_argument("--base-url", default="http://localhost:8000", help="S9 gateway base URL")
    p.add_argument(
        "--questions-file",
        default="tests/validation/chat_quality_benchmark/questions",
        help=(
            "Path to question catalogue. Accepts either a directory containing "
            "``*.yaml`` files (default — PLAN-0107 follow-up layout) or a single "
            ".yaml file (legacy mode). Directory entries are loaded in "
            "alpha-sorted filename order and concatenated."
        ),
    )
    p.add_argument("--tags", default="", help="Comma-separated tag filter (OR within tags)")
    p.add_argument("--ids", default="", help="Comma-separated question-id filter")
    p.add_argument(
        "--out-dir",
        default="tests/validation/chat_quality_benchmark/runs",
        help="Parent directory; the script appends a run_<ts> subdirectory.",
    )
    # NOTE: the old ``--concurrency`` flag was REMOVED (audit 2026-06-11 F9) —
    # it was advertised but never wired (the runner is strictly sequential), so
    # it silently lied about parallelism. Re-add it only alongside real
    # concurrency. TODO(PRD-scoring-redesign): parallel question execution.
    p.add_argument(
        "--baseline",
        default="",
        help=(
            "Path to a PRIOR run directory (run_<ts>) to diff against for the "
            "regression section. When omitted, the most recent prior run under "
            "the same --out-dir parent is auto-picked. Pass 'none' to disable."
        ),
    )
    # PLAN-0110 W4 (FR-15) — register a run as THE comparison baseline. When a
    # run_ts is given, the runner pins that existing run and exits (no chat run).
    # When the bare flag is passed (no value), the run produced by THIS
    # invocation becomes the baseline after it is appended to the store.
    p.add_argument(
        "--set-baseline",
        nargs="?",
        const="__current__",
        default=None,
        metavar="RUN_TS",
        help=(
            "Register a baseline for trend regression diffs (FR-15). Pass an "
            "existing run_ts to pin it (no chat run); pass the bare flag to pin "
            "THIS run after it completes. Only one baseline exists at a time."
        ),
    )
    p.add_argument(
        "--max-runs-per-q",
        type=int,
        default=3,
        help=(
            "Repeat each question N times to measure variance (PLAN-0107 v2.0). "
            "Default is 3 because mean+stddev are only meaningful with N>=2; a "
            "single run hides nondeterminism in LLM responses and routing. "
            "Set to 1 for a fast smoke run when you only care about pass/fail. "
            "This default has been reverted by parallel-session activity multiple "
            "times — keep at 3 unless you know what you are giving up."
        ),
    )
    p.add_argument("--timeout-s", type=float, default=120.0, help="Per-request HTTP timeout.")
    # PLAN-0104 W33 — LLM-judge integration.
    p.add_argument(
        "--judge",
        action="store_true",
        help="Run the LLM-judge rubric (PLAN-0104 W33) per question. Requires DEEPINFRA_API_KEY.",
    )
    # --- W2 trajectory layer ---
    # ``--trajectory`` / ``--no-trajectory`` toggles the tool-chain trajectory
    # judge. Default is None → resolved to ON whenever ``--judge`` is on (the
    # trajectory layer rides along with the answer judge). It never affects the
    # answer verdict; it only adds a ``trajectory`` block to the artefacts.
    p.add_argument(
        "--trajectory",
        dest="trajectory",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Grade the tool-chain TRAJECTORY (W2). Default: ON when --judge is set.",
    )
    p.add_argument(
        "--judge-only",
        action="store_true",
        help="Offline re-grade an existing --runs-dir without rerunning chat calls.",
    )
    p.add_argument(
        "--runs-dir",
        default="",
        help="When --judge-only is set, the existing run directory to re-grade in place.",
    )
    return p.parse_args(argv)


def _regrade_existing_run(runs_dir: Path) -> int:
    """Offline re-grade — read every ``q_<id>.json`` in ``runs_dir`` and add a
    fresh ``judge`` block + write ``_judge_summary.json``.

    Why this exists (PLAN-0104 W33): the chat call is expensive (LLM + 8+
    backend services) but the LLM-judge is a single short API call. We want
    to iterate on the rubric / prompt without rerunning the chat. This mode
    consumes only the captured artefacts, so it is also CI-safe.

    The legacy ``bucket`` + ``heuristics`` blocks are preserved untouched —
    we only overwrite the ``judge`` and ``rubric`` keys.
    """
    if not runs_dir.is_dir():
        print(f"ERROR: --runs-dir does not exist: {runs_dir}", file=sys.stderr)
        return 2

    # Load the original questions.yaml so we can look up each Q's rubric.
    # We trust the slot's ``id`` field over filename so renamed runs still work.
    q_files = sorted(runs_dir.glob("q_*.json"))
    if not q_files:
        print(f"ERROR: no q_*.json files in {runs_dir}", file=sys.stderr)
        return 2

    # PLAN-0107 follow-up: catalogue split into questions/*.yaml directory.
    questions_path = (_REPO_ROOT / "tests/validation/chat_quality_benchmark/questions").resolve()
    by_id = {q.get("id"): q for q in load_questions(questions_path) if q.get("id")}

    print(f"=== offline re-grade ===\nruns_dir : {runs_dir}\nfiles    : {len(q_files)}\n")
    judge_records: list[dict[str, Any]] = []
    for qf in q_files:
        try:
            payload = json.loads(qf.read_text())
        except json.JSONDecodeError as exc:
            print(f"  SKIP {qf.name} (malformed JSON: {exc})")
            continue
        q_id = payload.get("id")
        q_spec = by_id.get(q_id) or {}
        # Merge stored prompt back into q_spec so prompt drift in yaml never
        # silently degrades grading — the saved prompt is what was actually
        # asked.
        q_spec = {**q_spec, "prompt": payload.get("prompt") or q_spec.get("prompt")}
        result_dict = payload.get("result") or {}
        judge_input = build_input_from_artifact(q_spec, result_dict)
        judge_result = judge_answer(judge_input)
        payload["rubric"] = Rubric.from_question(q_spec).to_dict()
        payload["judge"] = judge_result
        qf.write_text(json.dumps(payload, indent=2, sort_keys=True))
        judge_records.append({"id": q_id, "slot": qf.stem, **judge_result})
        v, s = judge_result.get("verdict"), judge_result.get("score")
        print(f"  {q_id:<35} judge={v} score={s}")

    judge_summary = {
        "schema_version": _JUDGE_SUMMARY_SCHEMA_VERSION,
        # PLAN-0110 W3 (FR-12): stamp the judge identity on the offline re-grade
        # summary too, so a re-graded run records WHICH prompt/model/schema
        # produced its verdicts (the re-grade may use a newer judge than the
        # original chat run).
        "judge_prompt_version": CHAT_QUALITY_JUDGE.version,
        "judge_model_id": os.environ.get("CHAT_JUDGE_MODEL", _DEFAULT_JUDGE_MODEL),
        "verdict_model_version": VERDICT_MODEL_VERSION,
        "per_question": judge_records,
        **summarise_judge_records(judge_records),
    }
    (runs_dir / "_judge_summary.json").write_text(json.dumps(judge_summary, indent=2, sort_keys=True))
    agg = summarise_judge_records(judge_records)
    print()
    print(f"verdicts  : {agg['verdict_counts']}")
    print(f"score_avg : {agg['score_avg']}")
    print(f"dim_avg   : {agg['dimension_avg']}")
    print(f"summary   : {runs_dir / '_judge_summary.json'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # PLAN-0110 W4 (FR-15) — pin-an-existing-run mode. ``--set-baseline <run_ts>``
    # with a CONCRETE run_ts registers that run as the baseline and exits without
    # running any chat calls. The sentinel ``__current__`` (bare flag) is handled
    # AFTER the run completes, near the trend append.
    set_baseline_arg: str | None = getattr(args, "set_baseline", None)
    if set_baseline_arg is not None and set_baseline_arg != "__current__":
        store = TrendStore()
        if store.set_baseline(set_baseline_arg):
            print(f"baseline registered: {set_baseline_arg}")
            return 0
        print(f"ERROR: run_ts {set_baseline_arg!r} not found in trend store.", file=sys.stderr)
        return 2

    questions_path = (_REPO_ROOT / args.questions_file).resolve()
    # PLAN-0107 follow-up: accept directory (new layout) OR single .yaml file
    # (legacy). load_questions handles both transparently.
    if not questions_path.exists() or (not questions_path.is_file() and not questions_path.is_dir()):
        print(f"ERROR: questions path not found: {questions_path}", file=sys.stderr)
        return 2

    # PLAN-0104 W33 — offline re-grade mode. Skip the chat client entirely;
    # read existing q_<id>.json artefacts and overwrite them with the new
    # ``judge`` block + a freshly-written ``_judge_summary.json``.
    if args.judge_only:
        if not args.runs_dir:
            print("ERROR: --judge-only requires --runs-dir <path>", file=sys.stderr)
            return 2
        return _regrade_existing_run(Path(args.runs_dir).resolve())

    all_questions = load_questions(questions_path)
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] or None
    ids = [i.strip() for i in args.ids.split(",") if i.strip()] or None
    filtered = filter_questions(all_questions, tags=tags, ids=ids)

    if not filtered:
        print(f"ERROR: filters tags={tags} ids={ids} matched 0 of {len(all_questions)} questions.", file=sys.stderr)
        return 2

    run_ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = (_REPO_ROOT / args.out_dir / f"run_{run_ts}").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=== chat quality benchmark ===")
    print(f"base_url   : {args.base_url}")
    print(f"questions  : {len(filtered)} (of {len(all_questions)} after filters tags={tags} ids={ids})")
    print(f"runs/q     : {args.max_runs_per_q}")
    print(f"out_dir    : {out_dir}")
    print()

    client = _StandaloneClient(args.base_url, timeout_s=args.timeout_s)

    started_at = datetime.now(tz=UTC).isoformat()
    per_q_records: list[dict[str, Any]] = []
    bucket_counts = {"PASS": 0, "WARN": 0, "FAIL": 0, "EXCEPTION": 0}
    category_buckets: dict[str, dict[str, int]] = {}
    # PLAN-0104 W33 — per-Q judge records, aggregated into _judge_summary.json.
    judge_records: list[dict[str, Any]] = []
    # --- W2 trajectory layer ---
    # Trajectory grading rides along with the answer judge: ON when --judge is
    # set unless explicitly disabled with --no-trajectory. Its records aggregate
    # into the ``trajectory`` block of _judge_summary.json / the report.
    trajectory_enabled = args.judge and (args.trajectory is not False)
    trajectory_records: list[dict[str, Any]] = []

    try:
        for idx, q in enumerate(filtered):
            q_id = q.get("id") or f"unnamed_{idx}"
            category = q.get("category") or "uncategorized"
            for attempt in range(args.max_runs_per_q):
                slot = _safe_slot(q_id, attempt, args.max_runs_per_q)
                try:
                    result = client.ask(q.get("prompt") or "")
                    heur = compute_heuristics(q, result)
                    bucket, reasons = derive_pass_fail(heur)
                    # PLAN-0104 W33 — call the LLM judge per-Q when --judge is
                    # set. We grade after the chat call so a judge failure
                    # never affects the captured chat artefact.
                    judge_result: dict[str, Any] | None = None
                    if args.judge:
                        judge_input = JudgeInput(
                            prompt=q.get("prompt") or "",
                            rubric=Rubric.from_question(q),
                            answer_text=result.answer_text or "",
                            tool_calls=[{"name": tc.name, "arguments": tc.arguments} for tc in result.tool_calls],
                            tool_results=list(result.tool_results),
                        )
                        judge_result = judge_answer(judge_input)
                        judge_records.append({"id": q_id, "slot": slot, **judge_result})
                    # --- W2 trajectory layer ---
                    # Grade the tool-chain TRAJECTORY from the SAME JudgeInput the
                    # answer judge used (so both judges see the identical ordered
                    # trace). This NEVER mutates ``judge_result`` / the answer
                    # verdict — it is a separate ``trajectory`` block. We reuse
                    # ``judge_input`` from the --judge branch above; trajectory is
                    # only enabled when --judge is on, so it is always populated.
                    trajectory_result: dict[str, Any] | None = None
                    if trajectory_enabled:
                        trajectory_result = judge_trajectory(judge_input)
                        trajectory_records.append({"id": q_id, "slot": slot, **trajectory_result})
                    write_question_artifacts(
                        out_dir=out_dir,
                        slot=slot,
                        q=q,
                        result=result,
                        heur=heur,
                        bucket=bucket,
                        reasons=reasons,
                        judge_result=judge_result,
                        trajectory_result=trajectory_result,  # --- W2 trajectory layer ---
                    )
                    bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
                    cb = category_buckets.setdefault(category, {"PASS": 0, "WARN": 0, "FAIL": 0, "EXCEPTION": 0})
                    cb[bucket] = cb.get(bucket, 0) + 1
                    # PLAN-0099-W4: removed legacy heuristic fields
                    # (entities_mentioned, entities_missing, must_not_say_hits)
                    # from the per-Q summary — they no longer exist in the
                    # computed heuristics. The LLM judge replaces these checks.
                    per_q_records.append(
                        {
                            "id": q_id,
                            "slot": slot,
                            "category": category,
                            "bucket": bucket,
                            "reasons": reasons,
                            "latency_s": heur["latency_s"],
                            "ttft_s": heur["ttft_s"],
                            "word_count": heur["word_count"],
                            "tool_overlap_with_expected": heur["tool_overlap_with_expected"],
                            "missing_expected_tools": heur["missing_expected_tools"],
                            "is_refusal": heur["is_refusal"],
                            "is_empty": heur["is_empty"],
                        }
                    )
                    # PLAN-0104 W33 — append the judge verdict to the per-Q
                    # console line so the operator sees rubric grading inline.
                    judge_suffix = ""
                    if judge_result is not None:
                        v = judge_result.get("verdict")
                        s = judge_result.get("score")
                        judge_suffix = f" | judge={v} score={s}"
                    print(
                        f"[{idx + 1:>2}/{len(filtered)}] {q_id:<35} {bucket:<5} "
                        f"latency={heur['latency_s']:>5.1f}s words={heur['word_count']:>4} "
                        f"tools={','.join(heur['distinct_tools_called']) or '-'} "
                        f"{'; '.join(reasons) if reasons else ''}{judge_suffix}"
                    )
                except Exception as exc:  # — script-level catch-all
                    write_error_file(out_dir, slot, exc)
                    bucket_counts["EXCEPTION"] += 1
                    cb = category_buckets.setdefault(category, {"PASS": 0, "WARN": 0, "FAIL": 0, "EXCEPTION": 0})
                    cb["EXCEPTION"] = cb.get("EXCEPTION", 0) + 1
                    per_q_records.append(
                        {
                            "id": q_id,
                            "slot": slot,
                            "category": category,
                            "bucket": "EXCEPTION",
                            "reasons": [f"exception: {exc!r}"],
                        }
                    )
                    print(f"[{idx + 1:>2}/{len(filtered)}] {q_id:<35} EXCEPTION {exc!r}")
    finally:
        client.close()

    ended_at = datetime.now(tz=UTC).isoformat()

    meta = {
        "base_url": args.base_url,
        "questions_file": str(questions_path),
        "tags_filter": tags,
        "ids_filter": ids,
        "started_at": started_at,
        "ended_at": ended_at,
        "total_questions": len(filtered),
        "max_runs_per_q": args.max_runs_per_q,
        "total_runs": len(per_q_records),
        # Used by the Markdown renderer for the H1 heading.
        "out_dir_label": out_dir.name,
        # PLAN-0110 W3 (FR-12 / §6.4): stamp the exact judge identity on every
        # run so longitudinal comparisons (W4 trend store) can detect a verdict
        # discontinuity caused by a prompt re-word / model swap / schema bump —
        # not a genuine quality regression. ``judge_prompt_version`` is the
        # semver of CHAT_QUALITY_JUDGE; ``judge_prompt_id`` carries the
        # content-addressed identifier; ``judge_model_id`` is the LLM that
        # graded; ``verdict_model_version`` is the tiered-schema version.
        "judge_prompt_version": CHAT_QUALITY_JUDGE.version,
        "judge_prompt_id": CHAT_QUALITY_JUDGE.identifier(),
        "judge_model_id": os.environ.get("CHAT_JUDGE_MODEL", _DEFAULT_JUDGE_MODEL),
        "verdict_model_version": VERDICT_MODEL_VERSION,
    }
    (out_dir / "_meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True))

    summary = {
        "bucket_counts": bucket_counts,
        "category_buckets": category_buckets,
        "per_question": per_q_records,
    }
    (out_dir / "_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))

    # PLAN-0104 W33 — emit the judge aggregate when --judge was used.
    judge_summary: dict[str, Any] | None = None
    if args.judge:
        judge_summary = {
            "schema_version": _JUDGE_SUMMARY_SCHEMA_VERSION,
            "per_question": judge_records,
            **summarise_judge_records(judge_records),
        }
        # --- W2 trajectory layer ---
        # Roll the trajectory records into a ``trajectory`` block on the SAME
        # _judge_summary.json. {mean_score, redundant_turns_n, unrecovered_turns_n}
        # are the headline MUST-2 metrics; the full roll-up (dimension_avg, n_*)
        # rides alongside. Omitted entirely when trajectory grading was off.
        if trajectory_enabled:
            traj_roll = summarise_trajectory_records(trajectory_records)
            judge_summary["trajectory"] = {
                "mean_score": traj_roll["mean_score"],
                "redundant_turns_n": traj_roll["redundant_turns_n"],
                "unrecovered_turns_n": traj_roll["unrecovered_turns_n"],
                "dimension_avg": traj_roll["dimension_avg"],
                "n_records": traj_roll["n_records"],
                "n_graded": traj_roll["n_graded"],
                "judge_prompt_id": traj_roll["judge_prompt_id"],
                "per_question": trajectory_records,
            }
        (out_dir / "_judge_summary.json").write_text(json.dumps(judge_summary, indent=2, sort_keys=True))

    # PLAN-0099 W4 — write the human-readable report alongside the JSON
    # summaries. We re-read the q_*.json artefacts from disk (rather than
    # threading per-Q payloads through main()) so the renderer sees the same
    # structure the offline regrade mode produces. This is one disk pass at
    # the end of a long-running benchmark — well worth the simplicity.
    per_q_artifacts: list[dict[str, Any]] = []
    for q_file in sorted(out_dir.glob("q_*.json")):
        try:
            per_q_artifacts.append(json.loads(q_file.read_text()))
        except json.JSONDecodeError:
            # A malformed JSON would have been caught earlier; skip rather
            # than crashing report generation.
            continue

    # Resolve the baseline for the regression section (audit 2026-06-11).
    # --baseline <dir> wins; --baseline none disables; otherwise auto-pick the
    # most recent prior run under the out-dir parent.
    baseline_artifacts: list[dict[str, Any]] | None = None
    baseline_label: str | None = None
    baseline_arg = (args.baseline or "").strip()
    if baseline_arg.lower() != "none":
        baseline_dir: Path | None
        if baseline_arg:
            baseline_dir = Path(baseline_arg).resolve()
            if not baseline_dir.is_dir():
                print(f"WARN: --baseline {baseline_dir} is not a directory; skipping regression.", file=sys.stderr)
                baseline_dir = None
        else:
            baseline_dir = _autopick_baseline(out_dir.parent, out_dir)
        if baseline_dir is not None:
            baseline_artifacts = _load_run_artifacts(baseline_dir)
            baseline_label = baseline_dir.name

    # ── PLAN-0110 W4 — durable trend store append + store-backed regression ──
    # We append BEFORE rendering the report so the regression diff (which pulls
    # the rolling-window comparison from the store) sees a store that already
    # contains the prior runs, and so the report can embed the regression block.
    # Idempotent on run_ts: re-running the same run never duplicates rows.
    trend_store = TrendStore()
    question_rows = _artifact_question_rows(per_q_artifacts)
    run_row = _build_run_row(
        run_ts=run_ts,
        started_at=started_at,
        meta=meta,
        question_rows=question_rows,
    )
    regressions: dict[str, Any]
    try:
        # Compute the diff vs baseline + prior run BEFORE appending this run, so
        # the rolling-window lookup ("the run before this one") is not confused
        # by this run already being present.
        regressions = _compute_store_regressions(
            store=trend_store,
            run_ts=run_ts,
            current_rows=question_rows,
        )
        trend_store.append_run(run_row)
        # ``--set-baseline`` with the bare flag pins THIS run after it lands.
        if set_baseline_arg == "__current__":
            trend_store.set_baseline(run_ts)
            print(f"baseline registered: {run_ts}")
    except Exception as exc:  # — trend persistence must never sink a graded run
        # The jsonl sidecar backstop (F-5) already captured the rows on a SQLite
        # failure; surface a warning but keep the run artefacts/report intact.
        print(f"WARN: trend-store append failed: {exc!r}", file=sys.stderr)
        regressions = detect_regressions(
            current_rows=[],
            baseline_rows=None,
            baseline_label=None,
        )
    (out_dir / "_regressions.json").write_text(json.dumps(regressions, indent=2, sort_keys=True))

    # PLAN-0110 W5: the durable store-backed regression block (FR-15) is now
    # rendered AT THE TOP of the report (passed in via ``store_regressions``),
    # not appended at the bottom — so a reader sees regressions before any
    # average. ``_regressions.json`` (written above) is the machine-readable form.
    report_md = _render_report_md(
        meta=meta,
        summary=summary,
        judge_summary=judge_summary,
        per_question_artifacts=per_q_artifacts,
        baseline_artifacts=baseline_artifacts,
        baseline_label=baseline_label,
        store_regressions=regressions,
    )
    (out_dir / "_report.md").write_text(report_md)

    print()
    print("=== summary ===")
    print(f"buckets   : {bucket_counts}")
    for cat, counts in sorted(category_buckets.items()):
        print(f"  {cat:<20} {counts}")
    if args.judge and judge_records:
        agg = summarise_judge_records(judge_records)
        print(f"judge     : verdicts={agg['verdict_counts']} score_avg={agg['score_avg']}")
        print(f"            dimension_avg={agg['dimension_avg']}")
    # --- W2 trajectory layer ---
    if trajectory_enabled and trajectory_records:
        traj_agg = summarise_trajectory_records(trajectory_records)
        print(
            f"trajectory: mean_score={traj_agg['mean_score']} "
            f"redundant_turns={traj_agg['redundant_turns_n']} "
            f"unrecovered_turns={traj_agg['unrecovered_turns_n']}"
        )
    print(f"artifacts : {out_dir}")
    print(f"report    : {out_dir / '_report.md'}")
    print(f"trend     : {trend_store.sqlite_path} (+ {trend_store.jsonl_path.name})")
    print(f"regressions: {int(regressions.get('total_regressions') or 0)} (see {out_dir / '_regressions.json'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
