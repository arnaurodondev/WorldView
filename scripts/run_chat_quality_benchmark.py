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
"""

from __future__ import annotations

import argparse
import json
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
    JudgeInput,
    Rubric,
    build_input_from_artifact,
    judge_answer,
    summarise_judge_records,
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
    """Render a single Run section (## Run N) inside a per-question block."""
    result = art.get("result") or {}
    heur = art.get("heuristics") or {}
    judge = art.get("judge") or {}
    q_id = art.get("id") or "unknown"
    bucket = art.get("bucket") or "?"
    latency = float(result.get("latency_s") or heur.get("latency_s") or 0.0)
    words = int(heur.get("word_count") or 0)
    answer_text = str(result.get("answer_text") or "")
    tool_calls = result.get("tool_calls") or []
    tools = sorted({(tc.get("name") or "") for tc in tool_calls if isinstance(tc, dict)})

    # Headline: prefer judge verdict when present, else fall back to heuristic bucket.
    if judge:
        verdict = judge.get("verdict") or "?"
        score = judge.get("score")
        header = f"#### Run {run_idx} ({verdict}, {score}) — latency {latency:.1f}s, {words} words"
    else:
        header = f"#### Run {run_idx} ({bucket}) — latency {latency:.1f}s, {words} words"

    lines: list[str] = [header, ""]

    if tools:
        lines.append(f"**Tools called ({len(tools)}):** {', '.join(tools)}")
    else:
        lines.append("**Tools called:** *(none)*")
    lines.append("")

    lines.append("**Answer:**")
    lines.append("")
    # Use blockquote for readability; truncate long answers.
    truncated = _truncate_answer(answer_text, q_id)
    for line in truncated.splitlines() or [""]:
        lines.append(f"> {line}")
    lines.append("")

    if judge:
        v = judge.get("verdict") or "?"
        s = judge.get("score")
        lines.append(f"**Judge verdict:** {v} ({s}/100)")
        dims = judge.get("dimensions") or {}
        for k, payload in dims.items():
            if not isinstance(payload, dict):
                continue
            d_score = payload.get("score")
            d_feedback = _dim_field(payload, "feedback", "reason")
            tail = f" — {d_feedback}" if d_feedback else ""
            lines.append(f"- {k} {d_score}{tail}")
        # v2.0 reviewer_summary lives at the judge top level; v1.x used ``notes``.
        reviewer_summary = _dim_field(judge, "reviewer_summary", "notes")
        if reviewer_summary:
            lines.append("")
            lines.append(f"**Reviewer summary:** {reviewer_summary}")
    else:
        # No judge — surface the heuristic reasons so the run is still informative.
        reasons = art.get("reasons") or []
        if reasons:
            lines.append(f"**Heuristic reasons:** {'; '.join(reasons)}")

    lines.append("")
    return lines


def _render_question_block(q_id: str, artifacts: list[dict[str, Any]]) -> list[str]:
    """Render the per-question section (### Q<n>) with all its runs."""
    first = artifacts[0]
    category = first.get("category") or "uncategorized"
    prompt = first.get("prompt") or "(no prompt recorded)"

    # Aggregate stats across runs.
    judge_scores = [
        a["judge"].get("score")
        for a in artifacts
        if isinstance(a.get("judge"), dict) and isinstance(a["judge"].get("score"), int | float)
    ]
    verdicts = [a["judge"].get("verdict") for a in artifacts if isinstance(a.get("judge"), dict)]

    lines: list[str] = [f"### `{q_id}` ({category})", ""]
    lines.append("**Prompt:**")
    lines.append("")
    for line in prompt.splitlines():
        lines.append(f"> {line}")
    lines.append("")

    n = len(artifacts)
    if judge_scores:
        mean = statistics.mean(judge_scores)
        sd = _safe_stdev([float(s) for s in judge_scores])
        verdict_str = " ".join(verdicts) if verdicts else "?"
        lines.append(f"**Runs:** {n} — mean score **{mean:.1f}** (stddev {sd:.1f}); {verdict_str}")
    else:
        # No judge data — fall back to bucket roll-up.
        buckets = [a.get("bucket") or "?" for a in artifacts]
        lines.append(f"**Runs:** {n} — buckets: {' '.join(buckets)}")
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


def _render_report_md(
    *,
    meta: dict[str, Any],
    summary: dict[str, Any],
    judge_summary: dict[str, Any] | None,
    per_question_artifacts: list[dict[str, Any]],
) -> str:
    """Render a human-readable Markdown report for a benchmark run.

    Inputs are the in-memory dicts already produced by the runner — no I/O.
    ``per_question_artifacts`` is the list of ``q_<id>[_runN].json`` payloads
    (the runner passes them directly to avoid re-reading from disk).

    The report has four sections:
      1. Run header (timing, base URL, judge model, filters)
      2. Headline numbers (judge avg, verdict counts, dimension averages,
         legacy heuristic buckets)
      3. Per-question detail (one ### per question, then #### per run with
         answer + tools + judge feedback)
      4. Cross-question variance table + Errors section

    Supports both v2.0 judge schema (``feedback`` / ``reviewer_summary``) and
    v1.x (``reason`` / ``notes``) — falls back gracefully so old artefacts
    still render without crashing.
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

    # --- Headline numbers ----------------------------------------------
    lines.append("## Headline numbers")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    if judge_summary:
        score_avg = judge_summary.get("score_avg")
        score_avg_str = f"{score_avg:.2f} / 100" if isinstance(score_avg, int | float) else "-"
        lines.append(f"| Judge avg score | {score_avg_str} |")
        verdict_counts = judge_summary.get("verdict_counts") or {}
        verdict_str = " · ".join(f"{c} {v}" for v, c in verdict_counts.items() if c) or "(none)"
        lines.append(f"| Verdicts | {verdict_str} |")
        dim_avg = judge_summary.get("dimension_avg") or {}

        def _fmt_dim(v: Any) -> str:
            return f"{v:.1f}" if isinstance(v, int | float) else "-"

        dims_str = " · ".join(f"{k} {_fmt_dim(v)}" for k, v in dim_avg.items()) or "(none)"
        lines.append(f"| Dimensions | {dims_str} |")
    bucket_counts = (summary or {}).get("bucket_counts") or {}
    bucket_str = " · ".join(f"{c} {v}" for v, c in bucket_counts.items() if c) or "(none)"
    lines.append(f"| Heuristic buckets (legacy) | {bucket_str} |")
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
# Direct client (sidestep the pytest.skip plumbing in the harness)
# --------------------------------------------------------------------------


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
    p.add_argument("--concurrency", type=int, default=1, help="Currently sequential (>=1 reserved for future).")
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
        "schema_version": 1,
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
                    write_question_artifacts(
                        out_dir=out_dir,
                        slot=slot,
                        q=q,
                        result=result,
                        heur=heur,
                        bucket=bucket,
                        reasons=reasons,
                        judge_result=judge_result,
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
            "schema_version": 1,
            "per_question": judge_records,
            **summarise_judge_records(judge_records),
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
    report_md = _render_report_md(
        meta=meta,
        summary=summary,
        judge_summary=judge_summary,
        per_question_artifacts=per_q_artifacts,
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
    print(f"artifacts : {out_dir}")
    print(f"report    : {out_dir / '_report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
