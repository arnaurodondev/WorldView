"""Tests for the durable chat-quality trend store + regression diff (PLAN-0110 W4).

These are pure unit tests: every test points the ``TrendStore`` at a ``tmp_path``
so the COMMITTED store under ``tests/validation/chat_quality_benchmark/trend/`` is
never mutated. No chat client, no judge LLM, no subprocess.

Coverage (per the W4 validation gate):
* schema + indexes created on first write;
* run + question rows written and mirrored to the jsonl sidecar;
* **append idempotency** — the same ``run_ts`` twice == one row;
* sqlite-busy retry path;
* **regression detection** — a PASS→FAIL downgrade across two runs is flagged;
* quality-drop noise threshold (within == not flagged, beyond == flagged);
* ``--set-baseline`` registration (one baseline at a time);
* **empty-store first-run** — no prior run, no regressions, no crash.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import threading
from pathlib import Path

import pytest

# The trend module lives in scripts/ and is loaded by file path (mirrors the
# import style of the sibling test modules).
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS_DIR))

from chat_quality_trend import (
    QuestionRow,
    RunRow,
    TrendStore,
    detect_regressions,
)

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _qrow(
    qid: str,
    *,
    run_index: int = 0,
    verdict: str = "PASS",
    fail_reason: str | None = None,
    score: int = 80,
    contradicted: int = 0,
    latency_breach: int = 0,
) -> QuestionRow:
    return QuestionRow(
        question_id=qid,
        run_index=run_index,
        verdict=verdict,
        fail_reason=fail_reason,
        quality_score=score,
        dim_tool_use=20,
        dim_grounding=20,
        dim_framing=20,
        dim_refusal=20,
        grounding_contradicted=contradicted,
        latency_breach=latency_breach,
    )


def _run(
    run_ts: str,
    *,
    questions: list[QuestionRow] | None = None,
    is_baseline: int = 0,
) -> RunRow:
    qs = questions if questions is not None else [_qrow("q_alpha"), _qrow("q_beta")]
    counts = {"STRONG": 0, "PASS": 0, "WEAK": 0, "FAIL": 0}
    for q in qs:
        counts[q.verdict] = counts.get(q.verdict, 0) + 1
    mean = round(sum(q.quality_score for q in qs) / len(qs), 2) if qs else 0.0
    return RunRow(
        run_ts=run_ts,
        started_at="2026-06-12T10:00:00+00:00",
        judge_prompt_version="3.0",
        judge_model_id="deepseek-ai/DeepSeek-V4-Flash",
        verdict_model_version="1.1",
        n_questions=len(qs),
        n_pass=counts["PASS"],
        n_weak=counts["WEAK"],
        n_fail=counts["FAIL"],
        n_strong=counts["STRONG"],
        mean_quality_score=mean,
        is_baseline=is_baseline,
        questions=qs,
    )


@pytest.fixture
def store(tmp_path: Path) -> TrendStore:
    return TrendStore(trend_dir=tmp_path)


# ---------------------------------------------------------------------------
# Schema + append
# ---------------------------------------------------------------------------


def test_trend_schema_created(store: TrendStore) -> None:
    """Tables + both indexes exist after the schema is ensured."""
    store.ensure_schema()
    conn = sqlite3.connect(store.sqlite_path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    finally:
        conn.close()
    assert {"runs", "question_results"} <= tables
    assert {"ix_qr_question_run", "ix_qr_run"} <= indexes


def test_trend_append_run_and_questions(store: TrendStore) -> None:
    """A run writes one ``runs`` row + N ``question_results`` rows, mirrored to jsonl."""
    store.append_run(_run("20260612T100000Z"))

    run = store.get_run("20260612T100000Z")
    assert run is not None
    assert run["n_questions"] == 2
    assert run["judge_prompt_version"] == "3.0"

    q_rows = store.get_question_rows("20260612T100000Z")
    assert {r["question_id"] for r in q_rows} == {"q_alpha", "q_beta"}

    # jsonl sidecar mirrors the rows: 1 run line + 2 question lines.
    sidecar = store.jsonl_path.read_text().strip().splitlines()
    kinds = [json.loads(line)["kind"] for line in sidecar]
    assert kinds.count("run") == 1
    assert kinds.count("question") == 2


def test_trend_append_idempotent_same_run_ts(store: TrendStore) -> None:
    """Appending the SAME run_ts twice yields exactly one run + N question rows."""
    store.append_run(_run("20260612T100000Z"))
    # Re-append (e.g. a crash-retry or a --judge-only re-grade of the same run).
    store.append_run(_run("20260612T100000Z"))

    conn = sqlite3.connect(store.sqlite_path)
    try:
        n_runs = conn.execute("SELECT COUNT(*) FROM runs WHERE run_ts='20260612T100000Z'").fetchone()[0]
        n_qs = conn.execute(
            "SELECT COUNT(*) FROM question_results WHERE run_ts='20260612T100000Z'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n_runs == 1
    assert n_qs == 2

    # And the jsonl mirror has no duplicate run block either.
    kinds = [json.loads(line)["kind"] for line in store.jsonl_path.read_text().strip().splitlines()]
    assert kinds.count("run") == 1
    assert kinds.count("question") == 2


def test_trend_append_replaces_question_rows(store: TrendStore) -> None:
    """Re-appending a run_ts with different questions replaces (not merges) rows."""
    store.append_run(_run("20260612T100000Z", questions=[_qrow("q_alpha"), _qrow("q_beta")]))
    store.append_run(_run("20260612T100000Z", questions=[_qrow("q_gamma")]))
    q_rows = store.get_question_rows("20260612T100000Z")
    assert {r["question_id"] for r in q_rows} == {"q_gamma"}


def test_trend_busy_retry(store: TrendStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """A transient 'database is locked' is retried, not lost (F-5).

    We wrap a real connection so the FIRST attempt's ``BEGIN IMMEDIATE`` raises
    ``database is locked``; the second attempt uses a clean connection and lands.
    """
    store.ensure_schema()
    real_connect = store._connect
    calls = {"n": 0}

    class _LockOnceConn:
        """Proxy that raises on BEGIN for the first append attempt only."""

        def __init__(self, inner: sqlite3.Connection, fail: bool) -> None:
            self._inner = inner
            self._fail = fail

        def execute(self, sql: str, *a: object, **k: object) -> object:
            if self._fail and sql.strip().upper().startswith("BEGIN"):
                raise sqlite3.OperationalError("database is locked")
            return self._inner.execute(sql, *a, **k)

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

    def flaky_connect() -> sqlite3.Connection:
        calls["n"] += 1
        return _LockOnceConn(real_connect(), fail=(calls["n"] == 1))  # type: ignore[return-value]

    monkeypatch.setattr(store, "_connect", flaky_connect)
    store.append_run(_run("20260612T100000Z"))
    # Despite the first attempt being locked, the run landed.
    assert store.get_run("20260612T100000Z") is not None
    assert calls["n"] >= 2  # the retry actually happened


def test_trend_concurrent_appends_no_loss(tmp_path: Path) -> None:
    """Two threads appending distinct runs both land (busy-retry under contention)."""
    results: list[bool] = []

    def worker(ts: str) -> None:
        st = TrendStore(trend_dir=tmp_path)
        st.append_run(_run(ts))
        results.append(st.get_run(ts) is not None)

    t1 = threading.Thread(target=worker, args=("20260612T100000Z",))
    t2 = threading.Thread(target=worker, args=("20260612T100100Z",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert results == [True, True] or results == [True, True][::-1]
    final = TrendStore(trend_dir=tmp_path)
    assert final.get_run("20260612T100000Z") is not None
    assert final.get_run("20260612T100100Z") is not None


# ---------------------------------------------------------------------------
# Baseline registration (FR-15)
# ---------------------------------------------------------------------------


def test_set_baseline_marks_run(store: TrendStore) -> None:
    """``--set-baseline`` sets is_baseline=1 and clears any prior baseline."""
    store.append_run(_run("20260612T100000Z"))
    store.append_run(_run("20260612T100100Z"))

    assert store.set_baseline("20260612T100000Z") is True
    assert store.get_baseline_run_ts() == "20260612T100000Z"

    # Re-pointing the baseline clears the old one (only one at a time).
    assert store.set_baseline("20260612T100100Z") is True
    assert store.get_baseline_run_ts() == "20260612T100100Z"
    assert store.get_run("20260612T100000Z")["is_baseline"] == 0


def test_set_baseline_unknown_run(store: TrendStore) -> None:
    """Pinning a run_ts not in the store returns False (no-op)."""
    store.append_run(_run("20260612T100000Z"))
    assert store.set_baseline("nope") is False
    assert store.get_baseline_run_ts() is None


# ---------------------------------------------------------------------------
# Regression detection (FR-14)
# ---------------------------------------------------------------------------


def _rows(store: TrendStore, run_ts: str) -> list[dict[str, object]]:
    return store.get_question_rows(run_ts)


def test_trend_append_and_regression_diff_pass_to_fail(store: TrendStore) -> None:
    """A PASS→FAIL downgrade across two runs is flagged vs the baseline."""
    # Run 1: q_alpha PASS. Pin it as baseline.
    store.append_run(_run("20260612T100000Z", questions=[_qrow("q_alpha", verdict="PASS", score=82)]))
    store.set_baseline("20260612T100000Z")
    # Run 2: q_alpha now FAILs (control-token leak).
    store.append_run(
        _run(
            "20260612T100100Z",
            questions=[_qrow("q_alpha", verdict="FAIL", fail_reason="CONTROL_TOKEN_LEAK", score=40)],
        )
    )

    result = detect_regressions(
        current_rows=_rows(store, "20260612T100100Z"),
        baseline_rows=_rows(store, "20260612T100000Z"),
        baseline_label="20260612T100000Z",
    )
    assert result["has_regressions"] is True
    assert result["total_regressions"] == 1
    reg = result["baseline"]["regressions"][0]
    assert reg["question_id"] == "q_alpha"
    assert reg["verdict_from"] == "PASS"
    assert reg["verdict_to"] == "FAIL"
    assert reg["verdict_downgraded"] is True
    assert reg["new_invariant"] == "CONTROL_TOKEN_LEAK"


def test_regression_quality_drop_threshold(store: TrendStore) -> None:
    """A small score drop (within noise) is NOT flagged; a large one IS."""
    base = [_qrow("q_alpha", verdict="PASS", score=80)]
    # Within noise (-3): no verdict change, no flag.
    small = detect_regressions(
        current_rows=[
            {
                "question_id": "q_alpha",
                "run_index": 0,
                "verdict": "PASS",
                "fail_reason": None,
                "quality_score": 77,
                "grounding_contradicted": 0,
                "latency_breach": 0,
            }
        ],
        baseline_rows=[
            {
                "question_id": "q_alpha",
                "run_index": 0,
                "verdict": "PASS",
                "fail_reason": None,
                "quality_score": 80,
                "grounding_contradicted": 0,
                "latency_breach": 0,
            }
        ],
        baseline_label="base",
    )
    assert small["has_regressions"] is False

    # Beyond noise (-20) while still PASS: flagged on the score drop alone.
    big = detect_regressions(
        current_rows=[
            {
                "question_id": "q_alpha",
                "run_index": 0,
                "verdict": "PASS",
                "fail_reason": None,
                "quality_score": 60,
                "grounding_contradicted": 0,
                "latency_breach": 0,
            }
        ],
        baseline_rows=[
            {
                "question_id": "q_alpha",
                "run_index": 0,
                "verdict": "PASS",
                "fail_reason": None,
                "quality_score": 80,
                "grounding_contradicted": 0,
                "latency_breach": 0,
            }
        ],
        baseline_label="base",
    )
    assert big["has_regressions"] is True
    assert big["baseline"]["regressions"][0]["score_dropped"] is True
    # Silence the unused-fixture lint on ``base``.
    assert base[0].quality_score == 80


def test_regression_window_vs_baseline_both_diffed(store: TrendStore) -> None:
    """Both the registered baseline and the rolling window are diffed independently."""
    store.append_run(_run("20260612T100000Z", questions=[_qrow("q_alpha", verdict="STRONG", score=92)]))
    store.set_baseline("20260612T100000Z")
    store.append_run(_run("20260612T100100Z", questions=[_qrow("q_alpha", verdict="PASS", score=78)]))
    store.append_run(
        _run("20260612T100200Z", questions=[_qrow("q_alpha", verdict="FAIL", fail_reason="TRUNCATED", score=40)])
    )

    result = detect_regressions(
        current_rows=_rows(store, "20260612T100200Z"),
        baseline_rows=_rows(store, "20260612T100000Z"),
        baseline_label="20260612T100000Z",
        window_rows=_rows(store, "20260612T100100Z"),
        window_label="20260612T100100Z",
    )
    # STRONG→FAIL vs baseline AND PASS→FAIL vs the prior run: two regressions.
    assert result["baseline"]["regressions"][0]["verdict_from"] == "STRONG"
    assert result["window"]["regressions"][0]["verdict_from"] == "PASS"
    assert result["total_regressions"] == 2


def test_regression_empty_store_first_run() -> None:
    """First-ever run: no baseline, no window → no regressions, no crash (FR-14)."""
    result = detect_regressions(
        current_rows=[
            {
                "question_id": "q_alpha",
                "run_index": 0,
                "verdict": "PASS",
                "fail_reason": None,
                "quality_score": 80,
                "grounding_contradicted": 0,
                "latency_breach": 0,
            }
        ],
        baseline_rows=None,
        baseline_label=None,
        window_rows=None,
        window_label=None,
    )
    assert result["has_regressions"] is False
    assert result["total_regressions"] == 0
    assert result["baseline"]["available"] is False
    assert result["window"] is None


def test_recent_run_ts_before_excludes_current(store: TrendStore) -> None:
    """The rolling-window lookup returns the run immediately BEFORE the current one."""
    store.append_run(_run("20260612T100000Z"))
    store.append_run(_run("20260612T100100Z"))
    store.append_run(_run("20260612T100200Z"))
    prior = store.recent_run_ts(limit=1, before="20260612T100200Z")
    assert prior == ["20260612T100100Z"]
