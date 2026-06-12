#!/usr/bin/env python3
"""Durable longitudinal trend store for the chat-quality benchmark (PLAN-0110 W4).

Why this module exists
----------------------
Before W4 each benchmark run produced an isolated ``run_<ts>/`` directory and a
single ``--baseline`` diff that auto-picked *the most recent prior run*. That is
enough to eyeball "did this run get worse than the last one" but it is NOT a
durable record: there is no queryable history, no *registered* baseline you can
pin a thesis figure to, and no rolling-window view. PRD-0091 FR-13/14/15 ask for
a **durable, in-repo, committed trend store** so the thesis can claim a stable
longitudinal series and so a regression between two commits is caught
mechanically.

Design (AD-5 / NFR-5)
---------------------
* The store is a **single committed SQLite file** under the eval tree
  (``tests/validation/chat_quality_benchmark/trend/trend.sqlite``). It is NOT a
  service DB (R8/R9) — it is a dev-tool artefact that commits cleanly and is
  queryable with plain SQL for trend windows.
* Every row is *also* mirrored to an append-only newline-delimited JSON sidecar
  (``trend.jsonl``). The sidecar is the grep-able, lock-free backstop (F-5): if
  two parallel sessions ever contend on the SQLite file, the jsonl append never
  blocks and never loses a row.
* The schema follows PRD §6.4 EXACTLY (two tables ``runs`` + ``question_results``
  with the documented columns and the two indexes).

Determinism / diffability (the store is committed!)
---------------------------------------------------
A committed binary that churns on every run is a review nightmare, so we go out
of our way to keep writes deterministic:

* The ONLY timestamps written are ``run_ts`` and ``started_at`` — both PASSED IN
  by the runner (already computed once at run start). This module NEVER calls
  ``datetime.now()`` itself, so re-running the same logical run with the same
  ``run_ts`` produces byte-stable rows (no volatile "written_at" column).
* Appends are **idempotent**: writing the same ``run_ts`` twice replaces (not
  duplicates) the run + its question rows. This is what makes a ``--judge-only``
  re-grade of an existing run safe to re-run, and what stops a crash-retry from
  doubling rows.
* The jsonl sidecar is rewritten deterministically from the SQLite table after
  each append (stable row order: ``runs`` by ``run_ts``, then
  ``question_results`` ordered by ``(run_ts, question_id, run_index)``) so it,
  too, is diff-friendly rather than an ever-growing log with duplicate run_ts
  blocks.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# Paths (PRD §6.4) — the committed store lives under the eval tree.
# --------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
# The canonical committed location. Tests override this with a tmp_path so the
# committed artefact is never mutated by the test suite.
DEFAULT_TREND_DIR = _REPO_ROOT / "tests" / "validation" / "chat_quality_benchmark" / "trend"
TREND_SQLITE_NAME = "trend.sqlite"
TREND_JSONL_NAME = "trend.jsonl"

# Busy-retry budget for the short append transaction (F-5 / R42). SQLite raises
# ``OperationalError: database is locked`` under contention; we retry with a
# small backoff rather than losing the row. The jsonl sidecar is the ultimate
# backstop if even the retried transaction fails.
_BUSY_MAX_RETRIES = 8
_BUSY_BACKOFF_S = 0.05


# --------------------------------------------------------------------------
# Row dataclasses — typed carriers so the runner cannot silently drop a field
# (feedback_audit_returned_value_persistence: VerdictDecision fields MUST be
# persisted, not consumed only as a counter).
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class QuestionRow:
    """One (question, repeat) result within a run — mirrors ``question_results``."""

    question_id: str
    run_index: int
    verdict: str  # FAIL / WEAK / PASS / STRONG
    fail_reason: str | None  # InvariantCode when verdict=FAIL, else None
    quality_score: int  # 0-100 additive
    dim_tool_use: int
    dim_grounding: int
    dim_framing: int
    dim_refusal: int
    grounding_contradicted: int  # # numerically-contradicted claims (FR-6)
    latency_breach: int  # 1 if over budget


@dataclass(frozen=True)
class RunRow:
    """Run-level summary — mirrors the ``runs`` table (PRD §6.4)."""

    run_ts: str  # PK; UTC run-id (e.g. ``20260612T101500Z``)
    started_at: str  # ISO-8601 UTC (passed in by the runner)
    judge_prompt_version: str
    judge_model_id: str
    verdict_model_version: str
    n_questions: int
    n_pass: int
    n_weak: int
    n_fail: int
    n_strong: int
    mean_quality_score: float
    is_baseline: int = 0
    # The per-question rows belonging to this run. Not a DB column — carried here
    # so a single ``append_run`` call writes the whole run atomically.
    questions: list[QuestionRow] = field(default_factory=list)


# --------------------------------------------------------------------------
# DDL — created lazily on first connect. Matches PRD §6.4 column-for-column.
# --------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS runs (
    run_ts                TEXT NOT NULL PRIMARY KEY,
    started_at            TEXT NOT NULL,
    judge_prompt_version  TEXT NOT NULL,
    judge_model_id        TEXT NOT NULL,
    verdict_model_version TEXT NOT NULL,
    n_questions           INTEGER NOT NULL,
    n_pass                INTEGER NOT NULL,
    n_weak                INTEGER NOT NULL,
    n_fail                INTEGER NOT NULL,
    n_strong              INTEGER NOT NULL,
    mean_quality_score    REAL NOT NULL,
    is_baseline           INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS question_results (
    run_ts                 TEXT NOT NULL,
    question_id            TEXT NOT NULL,
    run_index              INTEGER NOT NULL,
    verdict                TEXT NOT NULL,
    fail_reason            TEXT,
    quality_score          INTEGER NOT NULL,
    dim_tool_use           INTEGER NOT NULL,
    dim_grounding          INTEGER NOT NULL,
    dim_framing            INTEGER NOT NULL,
    dim_refusal            INTEGER NOT NULL,
    grounding_contradicted INTEGER NOT NULL,
    latency_breach         INTEGER NOT NULL,
    PRIMARY KEY (run_ts, question_id, run_index),
    FOREIGN KEY (run_ts) REFERENCES runs (run_ts) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_qr_question_run ON question_results (question_id, run_ts);
CREATE INDEX IF NOT EXISTS ix_qr_run          ON question_results (run_ts);
"""


class TrendStore:
    """Append-only-by-run-ts SQLite trend store with a jsonl sidecar.

    All public methods open + close their own short-lived connection. We do NOT
    hold a long-lived connection because (a) the runner uses the store at most a
    couple of times per process and (b) short transactions are what makes the
    busy-retry strategy (F-5) work across parallel sessions.
    """

    def __init__(self, trend_dir: Path | str | None = None) -> None:
        self.trend_dir = Path(trend_dir) if trend_dir is not None else DEFAULT_TREND_DIR
        self.sqlite_path = self.trend_dir / TREND_SQLITE_NAME
        self.jsonl_path = self.trend_dir / TREND_JSONL_NAME

    # -- connection / schema ------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open a connection with FK enforcement + the schema ensured.

        ``timeout`` lets SQLite's own internal busy-handler wait a little before
        raising ``database is locked``; our explicit retry loop in ``append_run``
        handles the residual contention (F-5).
        """
        self.trend_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.sqlite_path, timeout=1.0)
        conn.row_factory = sqlite3.Row
        # FK ON so the CASCADE delete in the idempotent replace path works.
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_DDL)
        return conn

    def ensure_schema(self) -> None:
        """Create the tables + indexes if they don't exist (idempotent)."""
        conn = self._connect()
        try:
            conn.commit()
        finally:
            conn.close()

    # -- append (idempotent by run_ts) --------------------------------------

    def append_run(self, run: RunRow) -> None:
        """Append (or replace) one run + its question rows.

        Idempotency: re-appending the same ``run_ts`` deletes the prior run row
        (CASCADE wipes its question rows) and re-inserts — so the same logical
        run NEVER produces duplicate rows. This is the property the tests pin.

        Atomicity + busy-retry (F-5): the whole write is one transaction; on
        ``database is locked`` we back off and retry. After a successful commit
        we deterministically rewrite the jsonl sidecar from the table.
        """
        last_exc: sqlite3.OperationalError | None = None
        for attempt in range(_BUSY_MAX_RETRIES):
            conn = self._connect()
            try:
                # BEGIN IMMEDIATE takes the write lock up-front so a contended
                # write fails fast (and is retried) rather than half-applying.
                conn.execute("BEGIN IMMEDIATE")
                # Idempotent replace: drop the existing run (CASCADE removes its
                # question rows) before re-inserting.
                conn.execute("DELETE FROM runs WHERE run_ts = ?", (run.run_ts,))
                conn.execute(
                    """
                    INSERT INTO runs (
                        run_ts, started_at, judge_prompt_version, judge_model_id,
                        verdict_model_version, n_questions, n_pass, n_weak, n_fail,
                        n_strong, mean_quality_score, is_baseline
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.run_ts,
                        run.started_at,
                        run.judge_prompt_version,
                        run.judge_model_id,
                        run.verdict_model_version,
                        run.n_questions,
                        run.n_pass,
                        run.n_weak,
                        run.n_fail,
                        run.n_strong,
                        run.mean_quality_score,
                        run.is_baseline,
                    ),
                )
                conn.executemany(
                    """
                    INSERT INTO question_results (
                        run_ts, question_id, run_index, verdict, fail_reason,
                        quality_score, dim_tool_use, dim_grounding, dim_framing,
                        dim_refusal, grounding_contradicted, latency_breach
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            run.run_ts,
                            qr.question_id,
                            qr.run_index,
                            qr.verdict,
                            qr.fail_reason,
                            qr.quality_score,
                            qr.dim_tool_use,
                            qr.dim_grounding,
                            qr.dim_framing,
                            qr.dim_refusal,
                            qr.grounding_contradicted,
                            qr.latency_breach,
                        )
                        for qr in run.questions
                    ],
                )
                conn.commit()
                break
            except sqlite3.OperationalError as exc:
                # "database is locked" (and friends) → roll back + retry. Any
                # other OperationalError (e.g. a real schema bug) re-raises.
                conn.rollback()
                if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                    conn.close()
                    raise
                last_exc = exc
                conn.close()
                time.sleep(_BUSY_BACKOFF_S * (attempt + 1))
                continue
            finally:
                # ``conn`` may already be closed in the retry branch; closing a
                # closed connection is a no-op-ish ProgrammingError we swallow.
                try:
                    conn.close()
                except sqlite3.ProgrammingError:
                    pass
        else:
            # Exhausted retries — the jsonl sidecar is still our backstop, so we
            # write it from the in-memory row and re-raise so the caller knows
            # the durable SQLite write did not land.
            self._append_jsonl_rows(run)
            if last_exc is not None:
                raise last_exc
            return

        # Success: rewrite the jsonl sidecar deterministically from the table.
        self._rewrite_jsonl()

    # -- baseline registration (FR-15) --------------------------------------

    def set_baseline(self, run_ts: str) -> bool:
        """Pin ``run_ts`` as THE comparison baseline (FR-15).

        Only one baseline exists at a time: this clears ``is_baseline`` on every
        other run and sets it on the target. Returns False (no-op) if the target
        run is not in the store. The jsonl sidecar is rewritten so it stays in
        sync with the SQLite truth.
        """
        conn = self._connect()
        try:
            row = conn.execute("SELECT 1 FROM runs WHERE run_ts = ?", (run_ts,)).fetchone()
            if row is None:
                return False
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE runs SET is_baseline = 0 WHERE is_baseline = 1")
            conn.execute("UPDATE runs SET is_baseline = 1 WHERE run_ts = ?", (run_ts,))
            conn.commit()
        finally:
            conn.close()
        self._rewrite_jsonl()
        return True

    # -- reads --------------------------------------------------------------

    def get_baseline_run_ts(self) -> str | None:
        """Return the registered baseline ``run_ts`` (most recent if many)."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT run_ts FROM runs WHERE is_baseline = 1 ORDER BY run_ts DESC LIMIT 1"
            ).fetchone()
            return str(row["run_ts"]) if row is not None else None
        finally:
            conn.close()

    def get_run(self, run_ts: str) -> dict[str, Any] | None:
        """Return the ``runs`` row for ``run_ts`` as a plain dict, or None."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM runs WHERE run_ts = ?", (run_ts,)).fetchone()
            return dict(row) if row is not None else None
        finally:
            conn.close()

    def get_question_rows(self, run_ts: str) -> list[dict[str, Any]]:
        """Return all ``question_results`` rows for ``run_ts`` (stable order)."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM question_results WHERE run_ts = ? ORDER BY question_id, run_index",
                (run_ts,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def recent_run_ts(self, *, limit: int, before: str | None = None) -> list[str]:
        """Return up to ``limit`` run_ts ordered newest-first.

        ``before`` excludes the current run (and anything at/after it) so the
        rolling window is "the N runs *before* this one". run_ts is a sortable
        ``YYYYMMDDTHHMMSSZ`` string, so lexical ordering == chronological.
        """
        conn = self._connect()
        try:
            if before is not None:
                rows = conn.execute(
                    "SELECT run_ts FROM runs WHERE run_ts < ? ORDER BY run_ts DESC LIMIT ?",
                    (before, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT run_ts FROM runs ORDER BY run_ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [str(r["run_ts"]) for r in rows]
        finally:
            conn.close()

    # -- jsonl sidecar (deterministic mirror) -------------------------------

    def _rewrite_jsonl(self) -> None:
        """Rewrite the jsonl sidecar from the SQLite table, deterministically.

        We emit one line per ``runs`` row (tagged ``"kind": "run"``) followed by
        its ``question_results`` rows (tagged ``"kind": "question"``), ordered so
        the file is stable across re-runs. This is the grep-able, zero-tooling
        view of the store; it is regenerated from the SQLite source-of-truth so
        it never accumulates duplicate run_ts blocks.
        """
        conn = self._connect()
        try:
            run_rows = conn.execute("SELECT * FROM runs ORDER BY run_ts").fetchall()
            lines: list[str] = []
            for r in run_rows:
                rec: dict[str, Any] = {"kind": "run", **{k: r[k] for k in r.keys()}}
                lines.append(json.dumps(rec, sort_keys=True))
                q_rows = conn.execute(
                    "SELECT * FROM question_results WHERE run_ts = ? ORDER BY question_id, run_index",
                    (r["run_ts"],),
                ).fetchall()
                for q in q_rows:
                    qrec: dict[str, Any] = {"kind": "question", **{k: q[k] for k in q.keys()}}
                    lines.append(json.dumps(qrec, sort_keys=True))
        finally:
            conn.close()
        self.trend_dir.mkdir(parents=True, exist_ok=True)
        # Trailing newline so the file is a well-formed text file (and a clean
        # one-line-per-record diff).
        self.jsonl_path.write_text("\n".join(lines) + ("\n" if lines else ""))

    def _append_jsonl_rows(self, run: RunRow) -> None:
        """Lock-free backstop append (used only when SQLite write was lost).

        Unlike ``_rewrite_jsonl`` this appends the in-memory run without reading
        SQLite (which may be the contended resource). It can introduce a
        duplicate run_ts block, but a never-lost row is the priority of the
        backstop (F-5); the next successful ``append_run`` rewrites it clean.
        """
        self.trend_dir.mkdir(parents=True, exist_ok=True)
        run_dict = asdict(run)
        questions = run_dict.pop("questions")
        lines = [json.dumps({"kind": "run", **run_dict}, sort_keys=True)]
        for qr in questions:
            lines.append(json.dumps({"kind": "question", "run_ts": run.run_ts, **qr}, sort_keys=True))
        with self.jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------------
# Regression detection (FR-14): current run vs registered baseline + a rolling
# window. Pure functions over already-loaded rows so they are trivially
# testable (no DB, no LLM) and so the report (W5) can render the result.
# --------------------------------------------------------------------------

# Verdict severity ordering — higher number == worse. A regression is any move
# DOWN this ladder for the same question (e.g. PASS(1) → FAIL(3)).
_VERDICT_RANK = {"STRONG": 0, "PASS": 1, "WEAK": 2, "FAIL": 3}

# A quality_score drop below this magnitude is treated as run-to-run noise and
# is NOT flagged on its own (FR-14 "beyond a noise threshold"). A verdict
# downgrade or a new invariant is ALWAYS flagged regardless of score delta.
QUALITY_DROP_NOISE_THRESHOLD = 5


def _verdict_rank(verdict: str) -> int:
    """Severity rank for a verdict (unknown verdicts rank as worst)."""
    return _VERDICT_RANK.get(str(verdict).upper(), max(_VERDICT_RANK.values()))


def _index_questions(rows: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
    """Index question rows by (question_id, run_index) for pairwise diffing."""
    return {(str(r["question_id"]), int(r["run_index"])): r for r in rows}


def detect_regressions(
    *,
    current_rows: list[dict[str, Any]],
    baseline_rows: list[dict[str, Any]] | None,
    baseline_label: str | None,
    window_rows: list[dict[str, Any]] | None = None,
    window_label: str | None = None,
    quality_drop_threshold: int = QUALITY_DROP_NOISE_THRESHOLD,
) -> dict[str, Any]:
    """Diff ``current_rows`` vs a baseline and (optionally) a rolling window.

    For each (question_id, run_index) present in BOTH the current run and the
    reference we flag:
      * a **verdict downgrade** (e.g. PASS→WEAK/FAIL) — always flagged;
      * a **new invariant violation** (a ``fail_reason`` that wasn't present
        before, or grounding contradictions appearing) — always flagged;
      * a **quality_score drop** beyond ``quality_drop_threshold`` — flagged
        only when it clears the noise floor;
      * a **latency-breach increase** (0→1) — always flagged.

    Returns the ``_regressions.json`` shape (see module docstring / PRD §6.6.1).
    The structure is intentionally machine-readable AND directly renderable by
    the W5 report.
    """

    def _diff(reference_rows: list[dict[str, Any]] | None, label: str | None) -> dict[str, Any]:
        if not reference_rows:
            return {
                "label": label,
                "available": False,
                "shared_questions": 0,
                "regressions": [],
            }
        cur = _index_questions(current_rows)
        ref = _index_questions(reference_rows)
        shared = sorted(set(cur) & set(ref))
        regressions: list[dict[str, Any]] = []
        for key in shared:
            c = cur[key]
            r = ref[key]
            cur_verdict = str(c["verdict"]).upper()
            ref_verdict = str(r["verdict"]).upper()
            cur_score = int(c["quality_score"])
            ref_score = int(r["quality_score"])
            score_delta = cur_score - ref_score  # negative == got worse

            verdict_downgraded = _verdict_rank(cur_verdict) > _verdict_rank(ref_verdict)
            # A "new invariant" = a fail_reason now set that was not the prior
            # fail_reason, OR new numeric contradictions where there were none.
            cur_reason = c.get("fail_reason")
            ref_reason = r.get("fail_reason")
            new_invariant = bool(cur_reason) and cur_reason != ref_reason
            new_contradiction = int(c.get("grounding_contradicted") or 0) > int(
                r.get("grounding_contradicted") or 0
            )
            latency_regressed = int(c.get("latency_breach") or 0) > int(r.get("latency_breach") or 0)
            score_dropped = score_delta <= -quality_drop_threshold

            flagged = (
                verdict_downgraded
                or new_invariant
                or new_contradiction
                or latency_regressed
                or score_dropped
            )
            if not flagged:
                continue

            reasons: list[str] = []
            if verdict_downgraded:
                reasons.append(f"verdict {ref_verdict}->{cur_verdict}")
            if new_invariant:
                reasons.append(f"new invariant {cur_reason}")
            if new_contradiction:
                reasons.append("new grounding contradiction")
            if latency_regressed:
                reasons.append("latency breach")
            if score_dropped:
                reasons.append(f"score {score_delta:+d}")

            regressions.append(
                {
                    "question_id": key[0],
                    "run_index": key[1],
                    "verdict_from": ref_verdict,
                    "verdict_to": cur_verdict,
                    "verdict_downgraded": verdict_downgraded,
                    "score_from": ref_score,
                    "score_to": cur_score,
                    "score_delta": score_delta,
                    "score_dropped": score_dropped,
                    "new_invariant": cur_reason if new_invariant else None,
                    "new_contradiction": new_contradiction,
                    "latency_regressed": latency_regressed,
                    "reasons": reasons,
                }
            )
        return {
            "label": label,
            "available": True,
            "shared_questions": len(shared),
            "regressions": regressions,
        }

    baseline_diff = _diff(baseline_rows, baseline_label)
    window_diff = _diff(window_rows, window_label) if window_rows is not None else None

    total = len(baseline_diff["regressions"]) + (len(window_diff["regressions"]) if window_diff else 0)
    return {
        "quality_drop_threshold": quality_drop_threshold,
        "baseline": baseline_diff,
        "window": window_diff,
        "total_regressions": total,
        "has_regressions": total > 0,
    }
