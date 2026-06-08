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
    """Return a dict of advisory quality flags. No pass/fail decision here."""
    answer = result.answer_text or ""
    answer_lower = answer.lower()
    words = answer.split()

    expected_tools = set(q.get("expected_tools") or [])
    called_tools = set(result.tools_called())
    expected_entities = q.get("expected_entities_mentioned") or []
    must_not_say = q.get("must_not_say") or []

    # entity-mention check is substring + case-insensitive (entity tickers /
    # multi-word company names often render in mixed case from the LLM).
    mentioned = [e for e in expected_entities if e.lower() in answer_lower]
    missing = [e for e in expected_entities if e.lower() not in answer_lower]

    # forbidden-phrase scan; case-insensitive.
    forbidden_hits = [phrase for phrase in must_not_say if phrase.lower() in answer_lower]

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

    expected_max_latency = float(q.get("expected_max_latency_s") or 0.0) or None
    expected_min_words = int(q.get("expected_min_words") or 0)

    return {
        "is_empty": not answer.strip(),
        "is_refusal": is_refusal(answer),
        "word_count": len(words),
        "char_count": len(answer),
        "answer_meets_min_words": len(words) >= expected_min_words if expected_min_words else None,
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
        "entities_mentioned": mentioned,
        "entities_missing": missing,
        "must_not_say_hits": forbidden_hits,
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
    if heur["must_not_say_hits"]:
        reasons.append(f"forbidden_phrases={heur['must_not_say_hits']}")
        bucket = "FAIL"
    if heur["is_refusal"]:
        reasons.append("answer_classified_as_refusal")
        # refusal might be CORRECT (e.g. agg_a10 false-premise); leave at WARN
        # and let the human reader judge.
        if bucket != "FAIL":
            bucket = "WARN"
    if heur["entities_missing"]:
        reasons.append(f"missing_entities={heur['entities_missing']}")
        if bucket == "PASS":
            bucket = "WARN"
    if heur["answer_meets_min_words"] is False:
        reasons.append(f"short_answer words={heur['word_count']}")
        if bucket == "PASS":
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

    payload = {
        "id": q.get("id"),
        "prompt": q.get("prompt"),
        "category": q.get("category"),
        "tags": q.get("tags") or [],
        "expected": {
            "tools": q.get("expected_tools") or [],
            "entities": q.get("expected_entities_mentioned") or [],
            "numeric_class": q.get("expected_numeric_class"),
            "min_words": q.get("expected_min_words"),
            "max_latency_s": q.get("expected_max_latency_s"),
            "must_not_say": q.get("must_not_say") or [],
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
                            "entities_mentioned": heur["entities_mentioned"],
                            "entities_missing": heur["entities_missing"],
                            "must_not_say_hits": heur["must_not_say_hits"],
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
    }
    (out_dir / "_meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True))

    summary = {
        "bucket_counts": bucket_counts,
        "category_buckets": category_buckets,
        "per_question": per_q_records,
    }
    (out_dir / "_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))

    # PLAN-0104 W33 — emit the judge aggregate when --judge was used.
    if args.judge:
        judge_summary = {
            "schema_version": 1,
            "per_question": judge_records,
            **summarise_judge_records(judge_records),
        }
        (out_dir / "_judge_summary.json").write_text(json.dumps(judge_summary, indent=2, sort_keys=True))

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
    return 0


if __name__ == "__main__":
    sys.exit(main())
