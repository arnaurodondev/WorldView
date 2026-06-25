#!/usr/bin/env python3
"""GOLD-set assembly + Cohen's kappa calibration harness (PLAN-0110 W6).

Why this module exists
----------------------
PRD-0091 UC-3 / FR-9..FR-12 require the chat-quality judge to be *validated*: an
examiner must be able to see that the machine verdict agrees with a human on a
held-out, stratified GOLD set at a stated bar (Cohen's kappa >= 0.7), and — the
asymmetric part that actually matters for a finance agent — that the judge NEVER
marks a *fabricated* answer as PASS. A single kappa would hide that asymmetry, so
we report the full 2x2 confusion matrix and highlight the
false-PASS-on-fabrication cell explicitly (AD-6).

This module does two jobs, both pure-Python and offline (NFR-4 — no chat re-run,
no judge LLM, no network):

1. ``--assemble`` (W6-T-01): SAMPLE real captured per-question artefacts
   (``q_<id>[_runN].json``) from existing benchmark/eval run directories,
   stratify them by failure mode, and write an UNLABELLED gold set
   (``gold/gold_set.jsonl``) plus a paired blank ``gold/gold_labels.yaml`` for a
   human to fill in. We capture enough per item to re-grade offline: id, prompt,
   answer_text, tool_trace (tool_calls + tool_results incl. any grounding_sample),
   the rubric, and the CURRENT machine verdict (the tiered ``verdict_decision``
   when present, else the legacy v2 ``judge.dimensions`` + ``bucket``).

2. ``--calibrate`` (W6-T-03/04): once a human has labelled ``gold_labels.yaml``,
   compute Cohen's kappa (human PASS/FAIL vs machine verdict -> binary), raw
   agreement %, the 2x2 confusion matrix (false-PASS-on-fabrication highlighted),
   per-dimension MAE (human vs the four judge dims), and the acceptance gate
   (kappa >= 0.7 AND zero machine-PASS on any human-FAIL fabrication item). The
   report leads with accept/reject (FR-11) and is written to
   ``gold/_calibration_report.{md,json}``.

Both paths degrade gracefully on the *blank* (unlabelled) gold set: calibration
reports "0/N labelled — cannot compute" and exits without an exception so the
harness can be wired into CI before the human labelling session happens.

Architecture notes
------------------
* The gold/calibration artefacts live under ``tests/validation/`` — they are
  dev-tool fixtures, NEVER a service DB (R8/R9/AD-5).
* Timestamps use ``common.time.utc_now()`` (R11). ``scripts/**`` is exempt from
  the DTZ lint, but we still go through the shared helper for consistency.
* This module does NOT import or mutate ``chat_quality_judge.py`` /
  ``run_chat_quality_benchmark.py`` — it only *reads* their saved artefacts. The
  "current machine verdict" is whatever the artefact already recorded; this keeps
  calibration a pure read-side measurement of the shipped judge.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path / import bootstrap (mirrors run_chat_quality_benchmark.py).
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    # Shared UTC helper (R11). libs/common has no py.typed -> import-untyped.
    from common.time import utc_now  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - fallback when libs/common is not on the path

    def utc_now() -> datetime:
        """Fallback UTC clock if ``libs/common`` is not importable in this env."""
        return datetime.now(tz=UTC)


# ---------------------------------------------------------------------------
# Canonical gold-set locations + the five strata (OQ-2 RESOLVED).
# ---------------------------------------------------------------------------
GOLD_DIR = _REPO_ROOT / "tests" / "validation" / "chat_quality_benchmark" / "gold"
GOLD_SET_PATH = GOLD_DIR / "gold_set.jsonl"
GOLD_LABELS_PATH = GOLD_DIR / "gold_labels.yaml"
CALIBRATION_JSON_PATH = GOLD_DIR / "_calibration_report.json"
CALIBRATION_MD_PATH = GOLD_DIR / "_calibration_report.md"

# Where the assembler looks for real captured artefacts.
BENCHMARK_RUNS_DIR = _REPO_ROOT / "tests" / "validation" / "chat_quality_benchmark" / "runs"
CHAT_EVAL_RUNS_DIR = _REPO_ROOT / "tests" / "validation" / "chat_eval" / "runs"

# Failure-mode strata (OQ-2). The labels a human can also reproduce by eye.
STRATA: tuple[str, ...] = (
    "fabrication",  # answer states numbers the tools did not return (the false-PASS we must catch)
    "leak",  # control-token / fenced-stub leak (<function>, <tool_use>, <think>)
    "infra",  # all relevant tools transport_error/5xx + apology non-answer
    "good",  # genuinely grounded, useful answer
    "refusal",  # appropriate refusal (PII / future price / out-of-scope)
)

# The acceptance bar (OQ-4 RESOLVED).
KAPPA_BAR = 0.7

# The judge's four soft dimensions (the human also labels a fifth "coherence"
# dim per OQ-5; MAE is computed only over dims present on BOTH sides).
JUDGE_DIMS: tuple[str, ...] = ("tool_use", "grounding", "framing", "refusal_judgment")
# The label file uses "coherence" where the judge currently has "refusal_judgment";
# the human labels {tool_use, grounding, framing, coherence}. MAE maps coherence
# <-> the judge's fourth slot when comparing (documented in the README).
LABEL_DIMS: tuple[str, ...] = ("tool_use", "grounding", "framing", "coherence")


# ===========================================================================
# Part A — artefact reading + machine-verdict extraction
# ===========================================================================

# Regexes used ONLY to *stratify* (suggest a failure mode) during assembly — they
# never decide the calibration outcome; the human label and the recorded machine
# verdict do that. Kept deliberately conservative.
_LEAK_RE = re.compile(r"<function|<invoke|<think|<tool_use|</?antml:|<parameters>")
_APOLOGY_RE = re.compile(
    r"\b(sorry|apolog|unable|couldn't|could not|encountered an (error|issue)|"
    r"temporary (infrastructure|issue)|gateway timeout|try again|retry)\b",
    re.IGNORECASE,
)
# A refusal phrase is broader than an apology: "I cannot answer", "I can't
# predict", "is not available", "I don't have access". Used only for the refusal
# stratum hint.
_REFUSAL_RE = re.compile(
    r"\b(I (can('?t| ?not)|cannot|am unable|don'?t have|do not have)|"
    r"is (private|not available|not something)|unable to|not able to)\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\b\d[\d,\.]{2,}\b")
_OK_EMPTY = {"empty", "error", "transport_error", "timeout"}


def _dim_score(dimensions: Mapping[str, Any], key: str) -> int | None:
    """Read a judge dimension score from either the v2 (nested {'score': n}) or
    the v3 (flat int) artefact shape. Returns ``None`` when absent."""
    val = dimensions.get(key)
    if isinstance(val, Mapping):
        inner = val.get("score")
        return int(inner) if isinstance(inner, int | float) else None
    if isinstance(val, int | float):
        return int(val)
    return None


def extract_machine_verdict(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Project the CURRENT recorded machine verdict from a saved artefact.

    Tolerates both shapes:
    * v3 tiered: ``judge.verdict_decision`` carries ``verdict`` (STRONG/PASS/WEAK/
      FAIL), ``quality_score``, ``fail_reason``, ``gate_results``, ``dimensions``.
    * v2 legacy: only ``judge.dimensions`` (nested scores) + a top-level
      ``bucket`` (PASS/WARN/FAIL). We map WARN->WEAK for the tiered label.

    Returns a normalised dict with a binary ``machine_pass`` (the calibration
    target): tiered FAIL -> False, everything else (STRONG/PASS/WEAK) -> True,
    matching the W5 binary mapping (tiered FAIL == fail, otherwise pass).
    """
    judge = artifact.get("judge") or {}
    verdict_decision = judge.get("verdict_decision")
    if isinstance(verdict_decision, Mapping):
        dims = dict(verdict_decision.get("dimensions") or {})
        verdict = str(verdict_decision.get("verdict") or "FAIL")
        return {
            "verdict_model": "tiered",
            "verdict": verdict,
            "quality_score": verdict_decision.get("quality_score"),
            "fail_reason": verdict_decision.get("fail_reason"),
            "dimensions": {k: _dim_score({k: v}, k) for k, v in dims.items()},
            "machine_pass": verdict != "FAIL",
        }

    # Legacy v2 fallback.
    dimensions = judge.get("dimensions") or {}
    dim_scores = {k: _dim_score(dimensions, k) for k in dimensions}
    bucket = str(artifact.get("bucket") or "").upper()
    verdict_map = {"PASS": "PASS", "WARN": "WEAK", "FAIL": "FAIL"}
    verdict = verdict_map.get(bucket, "PASS" if dim_scores else "FAIL")
    quality = sum(v for v in dim_scores.values() if isinstance(v, int)) if dim_scores else None
    return {
        "verdict_model": "legacy_v2",
        "verdict": verdict,
        "quality_score": quality,
        "fail_reason": None,
        "dimensions": dim_scores,
        "machine_pass": verdict != "FAIL",
    }


def suggest_stratum(artifact: Mapping[str, Any]) -> str:
    """Heuristically classify an artefact into one of ``STRATA``.

    This is an *assembly aid only*. It picks a balanced, signal-rich sample; the
    HUMAN label is the ground truth used by calibration. Order matters: leak and
    infra are unambiguous textual signals, so they win over the numeric checks.
    """
    result = artifact.get("result") or {}
    answer = result.get("answer_text") or ""
    tool_results = result.get("tool_results") or []
    rubric = artifact.get("rubric") or {}

    if _LEAK_RE.search(answer):
        return "leak"

    statuses = [str(t.get("status")) for t in tool_results]
    if tool_results and all(s in _OK_EMPTY for s in statuses) and _APOLOGY_RE.search(answer) and len(answer) < 800:
        return "infra"

    if rubric.get("appropriate_refusal_ok") and (_REFUSAL_RE.search(answer[:400]) or _APOLOGY_RE.search(answer[:400])):
        return "refusal"

    grounding = _dim_score((artifact.get("judge") or {}).get("dimensions") or {}, "grounding")
    ok_items = sum(int(t.get("item_count") or 0) for t in tool_results if t.get("status") == "ok")
    numbers = len(_NUMBER_RE.findall(answer))
    if (isinstance(grounding, int) and grounding <= 12 and numbers >= 3) or (
        ok_items <= 1 and numbers >= 8 and len(answer) > 800
    ):
        return "fabrication"

    if isinstance(grounding, int) and grounding >= 22 and ok_items >= 2 and len(answer) > 400:
        return "good"

    return "other"


def build_gold_item(artifact: Mapping[str, Any], run_ref: str, item_id: str, stratum: str) -> dict[str, Any]:
    """Capture exactly the fields needed to re-grade this answer offline."""
    result = artifact.get("result") or {}
    return {
        "id": item_id,
        "question_id": artifact.get("id"),
        "run_ref": run_ref,
        "stratum": stratum,
        "prompt": artifact.get("prompt"),
        "answer_text": result.get("answer_text"),
        "tool_trace": {
            "tool_calls": result.get("tool_calls") or [],
            # tool_results may carry a grounding_sample once W2 capture is live;
            # absent on these (flag-off) artefacts — captured verbatim either way.
            "tool_results": result.get("tool_results") or [],
            "citations": result.get("citations") or [],
        },
        "rubric": artifact.get("rubric") or {},
        "machine_verdict": extract_machine_verdict(artifact),
    }


# ===========================================================================
# Part B — gold-set assembly (W6-T-01)
# ===========================================================================

# Target counts per stratum (~40 total, fabrication+leak deliberately over-
# weighted so the false-PASS-on-fabrication cell has signal — OQ-2 / risk row).
TARGET_COUNTS: dict[str, int] = {
    "fabrication": 9,
    "leak": 9,
    "infra": 8,
    "good": 8,
    "refusal": 6,
}


def _iter_artifacts(run_dirs: Sequence[Path]) -> Iterable[tuple[Path, Path]]:
    """Yield (run_dir, q_artifact_path) for every ``q_*.json`` under run_dirs."""
    for base in run_dirs:
        if not base.exists():
            continue
        for run_dir in sorted(base.iterdir()):
            if not run_dir.is_dir():
                continue
            yield from ((run_dir, p) for p in sorted(run_dir.glob("q_*.json")))


def assemble_gold_set(
    run_dirs: Sequence[Path] | None = None,
    targets: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Sample real artefacts into a stratified gold set (deterministic order).

    Greedy fill: walk every artefact once (sorted -> deterministic), classify it,
    and keep it while its stratum is under target. De-duplicate by (question_id,
    answer prefix) so three near-identical repeats of the same failing question do
    not all land in the set. Returns the assembled items (unlabelled).
    """
    run_dirs = list(run_dirs) if run_dirs is not None else [BENCHMARK_RUNS_DIR, CHAT_EVAL_RUNS_DIR]
    targets = dict(targets) if targets is not None else dict(TARGET_COUNTS)
    kept: dict[str, list[dict[str, Any]]] = {s: [] for s in targets}
    # De-dup by (question_id, answer-prefix) WITHIN one run only, so the same
    # question captured in *different* runs (a legitimately distinct snapshot —
    # different run_ts, possibly different tool outcome) can both contribute. This
    # is what fills the infra / refusal strata, which recur across the session's
    # many re-validation runs.
    seen: set[tuple[Any, Any, str]] = set()

    for run_dir, path in _iter_artifacts(run_dirs):
        if all(len(kept[s]) >= targets[s] for s in targets):
            break
        try:
            artifact = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        stratum = suggest_stratum(artifact)
        if stratum not in targets or len(kept[stratum]) >= targets[stratum]:
            continue
        answer = (artifact.get("result") or {}).get("answer_text") or ""
        dedup_key = (run_dir.name, artifact.get("id"), answer[:80])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        run_ref = f"{run_dir.parent.name}/{run_dir.name}/{path.name}"
        item_id = f"gold_{stratum}_{len([*kept[stratum]]) + 1:02d}"
        kept[stratum].append(build_gold_item(artifact, run_ref, item_id, stratum))

    # Flatten in a stable stratum order so the committed file is diff-stable.
    items: list[dict[str, Any]] = []
    for stratum in STRATA:
        items.extend(kept.get(stratum, []))
    return items


def write_gold_set(items: Sequence[Mapping[str, Any]], path: Path = GOLD_SET_PATH) -> None:
    """Write the gold set as JSONL (one item per line, sorted keys = diff-stable)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in items]
    path.write_text("\n".join(lines) + "\n")


def write_blank_labels(items: Sequence[Mapping[str, Any]], path: Path = GOLD_LABELS_PATH) -> None:
    """Write a blank, human-fillable ``gold_labels.yaml`` (one entry per item).

    We emit YAML *by hand* (no PyYAML dependency at assemble time) so the file is
    perfectly diff-stable and the blank schema is obvious to the human labeller.
    Each entry leaves ``human_verdict`` / dims / notes empty for the human, but
    echoes the machine verdict + stratum as an inline comment so the labeller has
    context without opening the (large) gold_set.jsonl.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    out: list[str] = [
        "# GOLD-set human labels (PLAN-0110 W6-T-02). FILL human_verdict + human_dims.",
        "# human_verdict: PASS | FAIL",
        "# human_dims: each 0-25 (tool_use, grounding, framing, coherence)",
        "# Leave labeler/labeled_at for the human. DO NOT edit `id` / ordering.",
        f"# Schema bar: kappa >= {KAPPA_BAR} AND zero machine-PASS on any human-FAIL fabrication item.",
        "labels:",
    ]
    for item in items:
        mv = item.get("machine_verdict") or {}
        out.append(f"  - id: {item['id']}")
        out.append(
            f"    # stratum={item.get('stratum')} machine_verdict={mv.get('verdict')} "
            f"machine_pass={mv.get('machine_pass')}"
        )
        out.append("    human_verdict:           # PASS | FAIL")
        out.append("    human_dims:")
        out.append("      tool_use:              # 0-25")
        out.append("      grounding:             # 0-25")
        out.append("      framing:               # 0-25")
        out.append("      coherence:             # 0-25")
        out.append("      labeler:")
        out.append("      labeled_at:")
        out.append("    notes:")
    path.write_text("\n".join(out) + "\n")


def stratification_counts(items: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Count items per stratum (for the README + assemble summary)."""
    counts: dict[str, int] = {s: 0 for s in STRATA}
    for item in items:
        counts[str(item.get("stratum"))] = counts.get(str(item.get("stratum")), 0) + 1
    return counts


# ===========================================================================
# Part C — label loader (W6-T-01b) — schema-validating, blank-tolerant
# ===========================================================================


@dataclass(frozen=True)
class GoldLabel:
    """One validated human label for a gold item."""

    item_id: str
    human_verdict: str | None  # "PASS" | "FAIL" | None (blank)
    human_dims: dict[str, int]  # may be empty when blank
    labeler: str | None
    labeled_at: str | None
    notes: str | None

    @property
    def is_labelled(self) -> bool:
        return self.human_verdict is not None


@dataclass(frozen=True)
class LabelSet:
    """A loaded ``gold_labels.yaml`` plus its labelled/total bookkeeping."""

    labels: dict[str, GoldLabel]
    total: int
    labelled: int
    errors: list[str] = field(default_factory=list)

    @property
    def fully_labelled(self) -> bool:
        return self.total > 0 and self.labelled == self.total and not self.errors

    def status_line(self) -> str:
        return f"{self.labelled}/{self.total} labelled"


def _coerce_verdict(raw: Any) -> str | None:
    """Validate a human_verdict cell: PASS/FAIL or blank. Raises on garbage."""
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return None
    text = str(raw).strip().upper()
    if text not in {"PASS", "FAIL"}:
        raise ValueError(f"human_verdict must be PASS or FAIL, got {raw!r}")
    return text


def _coerce_dims(raw: Any) -> dict[str, int]:
    """Validate the human_dims block: each present dim must be int in [0, 25]."""
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"human_dims must be a mapping, got {type(raw).__name__}")
    dims: dict[str, int] = {}
    for key in LABEL_DIMS:
        val = raw.get(key)
        if val is None or (isinstance(val, str) and val.strip() == ""):
            continue
        try:
            num = int(val)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"human_dims.{key} must be an int 0-25, got {val!r}") from exc
        if not 0 <= num <= 25:
            raise ValueError(f"human_dims.{key} out of range [0,25]: {num}")
        dims[key] = num
    return dims


def load_labels(path: Path = GOLD_LABELS_PATH) -> LabelSet:
    """Parse + schema-validate ``gold_labels.yaml``.

    Tolerates the *blank* unlabelled state: an entry with an empty
    ``human_verdict`` is recorded as "not labelled" rather than an error. Range /
    type violations on *populated* cells ARE errors. A partially labelled item
    (verdict set but a dim out of range) records an error for that item.
    """
    import yaml  # type: ignore[import-untyped]  # local import: PyYAML only needed for the loader

    raw = yaml.safe_load(path.read_text()) or {}
    entries = raw.get("labels") or []
    labels: dict[str, GoldLabel] = {}
    errors: list[str] = []
    labelled = 0

    for entry in entries:
        if not isinstance(entry, Mapping):
            errors.append(f"label entry is not a mapping: {entry!r}")
            continue
        item_id = str(entry.get("id") or "")
        if not item_id:
            errors.append(f"label entry missing id: {entry!r}")
            continue
        dims_block = entry.get("human_dims") or {}
        try:
            verdict = _coerce_verdict(entry.get("human_verdict"))
            dims = _coerce_dims(dims_block)
        except ValueError as exc:
            errors.append(f"{item_id}: {exc}")
            continue
        if verdict is not None:
            labelled += 1
        labels[item_id] = GoldLabel(
            item_id=item_id,
            human_verdict=verdict,
            human_dims=dims,
            labeler=(dims_block.get("labeler") if isinstance(dims_block, Mapping) else None),
            labeled_at=(dims_block.get("labeled_at") if isinstance(dims_block, Mapping) else None),
            notes=entry.get("notes"),
        )

    return LabelSet(labels=labels, total=len(labels), labelled=labelled, errors=errors)


def load_gold_items(path: Path = GOLD_SET_PATH) -> list[dict[str, Any]]:
    """Load the gold set (JSONL) back into memory."""
    items: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            items.append(json.loads(line))
    return items


# ===========================================================================
# Part D — calibration metrics (W6-T-03/04)
# ===========================================================================


def cohens_kappa(human: Sequence[str], machine: Sequence[str]) -> float:
    """Cohen's kappa for two raters over a 2-class label set (PASS/FAIL).

    kappa = (p_o - p_e) / (1 - p_e), where p_o is observed agreement and p_e is
    chance agreement from the marginal distributions. Returns 1.0 for perfect
    agreement, 0.0 for chance-level, negative for worse-than-chance. When p_e == 1
    (one rater used a single class for every item) kappa is undefined; we return
    1.0 iff the raters fully agree, else 0.0 (the conventional degenerate choice).
    """
    if len(human) != len(machine):
        raise ValueError("human and machine label sequences must be equal length")
    n = len(human)
    if n == 0:
        raise ValueError("cannot compute kappa over an empty label set")
    classes = ("PASS", "FAIL")
    agree = sum(1 for h, m in zip(human, machine, strict=False) if h == m)
    p_o = agree / n
    p_e = 0.0
    for cls in classes:
        p_h = sum(1 for h in human if h == cls) / n
        p_m = sum(1 for m in machine if m == cls) / n
        p_e += p_h * p_m
    if p_e >= 1.0:
        return 1.0 if agree == n else 0.0
    return (p_o - p_e) / (1.0 - p_e)


@dataclass(frozen=True)
class ConfusionMatrix:
    """2x2 confusion matrix (human truth x machine prediction) over PASS/FAIL.

    The cell that matters for a finance agent is ``false_pass_fabrication``:
    items a human labelled FAIL *and* tagged as the fabrication stratum that the
    machine still called PASS. A non-empty cell is an automatic reject (OQ-4).
    """

    machine_pass_human_pass: int  # true PASS
    machine_pass_human_fail: int  # FALSE PASS (machine too lenient)
    machine_fail_human_pass: int  # false FAIL (machine too strict)
    machine_fail_human_fail: int  # true FAIL
    false_pass_fabrication_ids: list[str]

    @property
    def total(self) -> int:
        return (
            self.machine_pass_human_pass
            + self.machine_pass_human_fail
            + self.machine_fail_human_pass
            + self.machine_fail_human_fail
        )

    @property
    def agreement(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.machine_pass_human_pass + self.machine_fail_human_fail) / self.total


def build_confusion_matrix(
    rows: Sequence[Mapping[str, Any]],
) -> ConfusionMatrix:
    """Build the 2x2 matrix from joined rows.

    Each ``row`` carries: ``human_verdict`` (PASS/FAIL), ``machine_pass`` (bool),
    ``stratum`` (str). The fabrication false-PASS cell is the union of FALSE-PASS
    rows whose stratum == 'fabrication'.
    """
    tp = fp = fn = tn = 0
    fab_false_pass: list[str] = []
    for row in rows:
        human = str(row["human_verdict"])
        machine_pass = bool(row["machine_pass"])
        if machine_pass and human == "PASS":
            tp += 1
        elif machine_pass and human == "FAIL":
            fp += 1
            if str(row.get("stratum")) == "fabrication":
                fab_false_pass.append(str(row.get("id")))
        elif not machine_pass and human == "PASS":
            fn += 1
        else:
            tn += 1
    return ConfusionMatrix(
        machine_pass_human_pass=tp,
        machine_pass_human_fail=fp,
        machine_fail_human_pass=fn,
        machine_fail_human_fail=tn,
        false_pass_fabrication_ids=fab_false_pass,
    )


def per_dimension_mae(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Mean absolute error per dimension (human label vs judge dim score).

    Only dims present on BOTH sides for a row contribute. The judge's
    ``refusal_judgment`` slot maps to the human ``coherence`` label (OQ-5 — the
    coherence dim replaces refusal as a soft dim); all four are compared by their
    label name (``tool_use``/``grounding``/``framing``/``coherence``).
    """
    sums: dict[str, float] = {d: 0.0 for d in LABEL_DIMS}
    counts: dict[str, int] = {d: 0 for d in LABEL_DIMS}
    for row in rows:
        human_dims = row.get("human_dims") or {}
        machine_dims = row.get("machine_dims") or {}
        for label_dim in LABEL_DIMS:
            h = human_dims.get(label_dim)
            # coherence maps onto the judge's fourth slot (refusal_judgment).
            judge_key = "refusal_judgment" if label_dim == "coherence" else label_dim
            m = machine_dims.get(judge_key)
            if isinstance(h, int | float) and isinstance(m, int | float):
                sums[label_dim] += abs(float(h) - float(m))
                counts[label_dim] += 1
    return {d: (sums[d] / counts[d]) if counts[d] else float("nan") for d in LABEL_DIMS}


# ===========================================================================
# Part E — calibration driver + acceptance gate
# ===========================================================================


def join_rows(items: Sequence[Mapping[str, Any]], label_set: LabelSet) -> list[dict[str, Any]]:
    """Join gold items to their human labels (labelled items only)."""
    rows: list[dict[str, Any]] = []
    for item in items:
        label = label_set.labels.get(str(item.get("id")))
        if label is None or not label.is_labelled:
            continue
        mv = item.get("machine_verdict") or {}
        rows.append(
            {
                "id": item.get("id"),
                "stratum": item.get("stratum"),
                "human_verdict": label.human_verdict,
                "human_dims": label.human_dims,
                "machine_pass": bool(mv.get("machine_pass")),
                "machine_verdict": mv.get("verdict"),
                "machine_dims": mv.get("dimensions") or {},
            }
        )
    return rows


def evaluate_calibration(
    items: Sequence[Mapping[str, Any]],
    label_set: LabelSet,
    kappa_bar: float = KAPPA_BAR,
) -> dict[str, Any]:
    """Compute the full calibration result + accept/reject gate.

    Blank-set behaviour: if no item is labelled, returns ``computable=False`` with
    a human-readable status ("0/N labelled — cannot compute") and ``accepted``
    omitted — NO exception. This is what lets the harness run in CI before the
    human labelling session.
    """
    result: dict[str, Any] = {
        "computed_at": utc_now().isoformat(),
        "kappa_bar": kappa_bar,
        "label_status": label_set.status_line(),
        "n_total": label_set.total,
        "n_labelled": label_set.labelled,
        "loader_errors": list(label_set.errors),
    }

    rows = join_rows(items, label_set)
    if not rows:
        result["computable"] = False
        result["reason"] = f"{label_set.labelled}/{label_set.total} labelled — cannot compute"
        return result

    human = [str(r["human_verdict"]) for r in rows]
    machine = ["PASS" if r["machine_pass"] else "FAIL" for r in rows]
    kappa = cohens_kappa(human, machine)
    matrix = build_confusion_matrix(rows)
    mae = per_dimension_mae(rows)
    fab_false_pass = matrix.false_pass_fabrication_ids

    kappa_ok = kappa >= kappa_bar
    no_fab_false_pass = len(fab_false_pass) == 0
    accepted = kappa_ok and no_fab_false_pass

    result.update(
        {
            "computable": True,
            "n_compared": len(rows),
            "kappa": round(kappa, 4),
            "agreement": round(matrix.agreement, 4),
            "confusion_matrix": {
                "true_pass": matrix.machine_pass_human_pass,
                "false_pass": matrix.machine_pass_human_fail,
                "false_fail": matrix.machine_fail_human_pass,
                "true_fail": matrix.machine_fail_human_fail,
                "false_pass_on_fabrication": fab_false_pass,
            },
            "per_dimension_mae": {k: (None if v != v else round(v, 3)) for k, v in mae.items()},
            "gate": {
                "kappa_ok": kappa_ok,
                "no_fabrication_false_pass": no_fab_false_pass,
            },
            "accepted": accepted,
        }
    )
    return result


def render_calibration_md(result: Mapping[str, Any]) -> str:
    """Render the human-facing calibration report (accept/reject leads — FR-11)."""
    lines: list[str] = ["# Chat-Quality Judge — Calibration Report", ""]
    lines.append(f"_computed_at_: `{result.get('computed_at')}`  ")
    lines.append(f"_labels_: **{result.get('label_status')}**")
    lines.append("")

    if not result.get("computable"):
        lines.append("## ⏳ Not yet computable")
        lines.append("")
        lines.append(f"> {result.get('reason')}")
        lines.append("")
        if result.get("loader_errors"):
            lines.append("### Loader errors")
            for err in result["loader_errors"]:
                lines.append(f"- {err}")
        return "\n".join(lines) + "\n"

    accepted = result.get("accepted")
    headline = "✅ ACCEPT" if accepted else "⛔ REJECT"
    lines.append(f"## {headline} (bar: κ ≥ {result.get('kappa_bar')} AND zero false-PASS-on-fabrication)")
    lines.append("")
    cm = result["confusion_matrix"]
    fab = cm["false_pass_on_fabrication"]
    lines.append(
        f"- Cohen's κ: **{result['kappa']}** " f"({'≥' if result['gate']['kappa_ok'] else '<'} {result['kappa_bar']})"
    )
    lines.append(f"- Raw agreement: {result['agreement']}")
    lines.append(f"- Items compared: {result['n_compared']}")
    fab_line = "none ✅" if not fab else f"**{len(fab)} → {', '.join(fab)}** ⛔"
    lines.append(f"- False-PASS on fabrication: {fab_line}")
    lines.append("")
    lines.append("## Confusion matrix (human truth x machine)")
    lines.append("")
    lines.append("| | machine PASS | machine FAIL |")
    lines.append("|---|---|---|")
    lines.append(f"| **human PASS** | {cm['true_pass']} (TP) | {cm['false_fail']} (false-FAIL) |")
    fab_cell = f"{cm['false_pass']} (FALSE-PASS)" + (" ⛔ FABRICATION" if fab else "")
    lines.append(f"| **human FAIL** | {fab_cell} | {cm['true_fail']} (TN) |")
    lines.append("")
    lines.append("## Per-dimension MAE (human vs judge dim)")
    lines.append("")
    lines.append("| dimension | MAE |")
    lines.append("|---|---|")
    for dim, val in result["per_dimension_mae"].items():
        lines.append(f"| {dim} | {'n/a' if val is None else val} |")
    return "\n".join(lines) + "\n"


def run_calibration(
    gold_set_path: Path = GOLD_SET_PATH,
    labels_path: Path = GOLD_LABELS_PATH,
    json_out: Path = CALIBRATION_JSON_PATH,
    md_out: Path = CALIBRATION_MD_PATH,
) -> dict[str, Any]:
    """End-to-end: load gold + labels, compute, write both reports, return result."""
    items = load_gold_items(gold_set_path)
    label_set = load_labels(labels_path)
    result = evaluate_calibration(items, label_set)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    md_out.write_text(render_calibration_md(result))
    return result


# ===========================================================================
# CLI
# ===========================================================================


def _cmd_assemble(args: argparse.Namespace) -> int:
    items = assemble_gold_set()
    counts = stratification_counts(items)
    write_gold_set(items)
    write_blank_labels(items)
    print("=== gold-set assembly ===")  # - CLI output
    print(f"items     : {len(items)}")
    for stratum in STRATA:
        print(f"  {stratum:12s}: {counts.get(stratum, 0)}")
    print(f"gold_set  : {GOLD_SET_PATH}")
    print(f"labels    : {GOLD_LABELS_PATH} (BLANK — human fills next)")
    return 0


def _cmd_calibrate(args: argparse.Namespace) -> int:
    result = run_calibration()
    print(render_calibration_md(result))  # - CLI output
    print(f"json: {CALIBRATION_JSON_PATH}")
    print(f"md  : {CALIBRATION_MD_PATH}")
    # Exit non-zero only when computable AND rejected (so blank-set CI stays green).
    if result.get("computable") and not result.get("accepted"):
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chat-quality GOLD set + κ calibration (PLAN-0110 W6).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_assemble = sub.add_parser("assemble", help="Assemble the unlabelled stratified gold set.")
    p_assemble.set_defaults(func=_cmd_assemble)

    p_calibrate = sub.add_parser("calibrate", help="Compute κ + confusion + MAE + accept/reject.")
    p_calibrate.set_defaults(func=_cmd_calibrate)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
