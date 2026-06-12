"""Tests for the GOLD-set + Cohen's κ calibration harness (PLAN-0110 W6).

Pure unit tests — no chat client, no judge LLM, no network. Every test that
touches files uses ``tmp_path`` so the COMMITTED gold set under
``tests/validation/chat_quality_benchmark/gold/`` is never mutated.

Coverage (per the W6 validation gate):
* Cohen's κ on a SYNTHETIC labelled fixture with a known κ;
* the 2x2 confusion matrix + the false-PASS-on-fabrication cell;
* per-dimension MAE;
* the acceptance gate — pass case AND both fail cases (κ-below-bar, fabrication
  false-PASS);
* blank-set graceful "0/N labelled — cannot compute";
* loader schema validation — out-of-range dim, bad verdict, missing id, blank
  tolerance, partial labelling count;
* machine-verdict extraction from both the v2 (legacy bucket) and v3 (tiered
  verdict_decision) artefact shapes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# The calibration module lives in scripts/ alongside this test's parent.
_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import chat_quality_calibration as cal

# ---------------------------------------------------------------------------
# Cohen's κ — synthetic fixture with a hand-computable answer.
# ---------------------------------------------------------------------------


def test_kappa_perfect_agreement() -> None:
    human = ["PASS", "FAIL", "PASS", "FAIL"]
    machine = ["PASS", "FAIL", "PASS", "FAIL"]
    assert cal.cohens_kappa(human, machine) == pytest.approx(1.0)


def test_kappa_known_value() -> None:
    # 10 items. Confusion: human/machine
    #   PASS/PASS = 4, FAIL/FAIL = 3, PASS/FAIL = 2, FAIL/PASS = 1
    # p_o = (4+3)/10 = 0.70
    # marginals: human PASS=6, FAIL=4 ; machine PASS=5, FAIL=5
    # p_e = 0.6*0.5 + 0.4*0.5 = 0.50
    # κ = (0.70-0.50)/(1-0.50) = 0.40
    human = ["PASS"] * 6 + ["FAIL"] * 4
    machine = ["PASS"] * 4 + ["FAIL"] * 2 + ["PASS"] * 1 + ["FAIL"] * 3
    assert cal.cohens_kappa(human, machine) == pytest.approx(0.40, abs=1e-9)


def test_kappa_chance_level_is_zero() -> None:
    # Independent raters with the same 50/50 marginal → κ ≈ 0.
    human = ["PASS", "FAIL", "PASS", "FAIL"]
    machine = ["PASS", "PASS", "FAIL", "FAIL"]  # p_o=0.5, p_e=0.5 → κ=0
    assert cal.cohens_kappa(human, machine) == pytest.approx(0.0, abs=1e-9)


def test_kappa_single_class_degenerate() -> None:
    # Both raters used only PASS → p_e == 1; full agreement → 1.0.
    assert cal.cohens_kappa(["PASS", "PASS"], ["PASS", "PASS"]) == 1.0
    # One rater all PASS, other mixed → p_e==1 path, not full agreement → 0.0.
    assert cal.cohens_kappa(["PASS", "PASS"], ["PASS", "FAIL"]) == 0.0


def test_kappa_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="equal length"):
        cal.cohens_kappa(["PASS"], ["PASS", "FAIL"])


def test_kappa_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        cal.cohens_kappa([], [])


# ---------------------------------------------------------------------------
# Confusion matrix + false-PASS-on-fabrication cell.
# ---------------------------------------------------------------------------


def _row(item_id: str, human: str, machine_pass: bool, stratum: str = "good") -> dict:
    return {"id": item_id, "human_verdict": human, "machine_pass": machine_pass, "stratum": stratum}


def test_confusion_matrix_cells() -> None:
    rows = [
        _row("a", "PASS", True),  # TP
        _row("b", "FAIL", False),  # TN
        _row("c", "PASS", False),  # false-FAIL
        _row("d", "FAIL", True),  # FALSE-PASS (not fabrication)
    ]
    cm = cal.build_confusion_matrix(rows)
    assert cm.machine_pass_human_pass == 1
    assert cm.machine_fail_human_fail == 1
    assert cm.machine_fail_human_pass == 1
    assert cm.machine_pass_human_fail == 1
    assert cm.false_pass_fabrication_ids == []
    assert cm.total == 4
    assert cm.agreement == pytest.approx(0.5)


def test_confusion_matrix_fabrication_false_pass_cell() -> None:
    rows = [
        _row("fab1", "FAIL", True, stratum="fabrication"),  # FALSE-PASS on fabrication ⛔
        _row("fab2", "FAIL", False, stratum="fabrication"),  # correctly failed
        _row("g1", "PASS", True, stratum="good"),
    ]
    cm = cal.build_confusion_matrix(rows)
    assert cm.false_pass_fabrication_ids == ["fab1"]
    assert cm.machine_pass_human_fail == 1


# ---------------------------------------------------------------------------
# Per-dimension MAE (coherence ↔ refusal_judgment mapping).
# ---------------------------------------------------------------------------


def test_per_dim_mae() -> None:
    rows = [
        {
            "human_dims": {"tool_use": 25, "grounding": 10, "framing": 20, "coherence": 15},
            # machine uses the judge's fourth slot name for coherence.
            "machine_dims": {"tool_use": 25, "grounding": 25, "framing": 25, "refusal_judgment": 25},
        },
        {
            "human_dims": {"tool_use": 20, "grounding": 20, "framing": 20, "coherence": 20},
            "machine_dims": {"tool_use": 25, "grounding": 20, "framing": 15, "refusal_judgment": 20},
        },
    ]
    mae = cal.per_dimension_mae(rows)
    # tool_use: |25-25|=0, |20-25|=5 → mean 2.5
    assert mae["tool_use"] == pytest.approx(2.5)
    # grounding: |10-25|=15, |20-20|=0 → mean 7.5
    assert mae["grounding"] == pytest.approx(7.5)
    # framing: |20-25|=5, |20-15|=5 → mean 5.0
    assert mae["framing"] == pytest.approx(5.0)
    # coherence vs refusal_judgment: |15-25|=10, |20-20|=0 → mean 5.0
    assert mae["coherence"] == pytest.approx(5.0)


def test_per_dim_mae_missing_dim_is_nan() -> None:
    rows = [{"human_dims": {"tool_use": 20}, "machine_dims": {"grounding": 25}}]
    mae = cal.per_dimension_mae(rows)
    assert mae["grounding"] != mae["grounding"]  # NaN where no overlap


# ---------------------------------------------------------------------------
# Machine-verdict extraction (v2 legacy + v3 tiered shapes).
# ---------------------------------------------------------------------------


def test_extract_machine_verdict_v3_tiered() -> None:
    artifact = {
        "judge": {
            "verdict_decision": {
                "verdict": "FAIL",
                "quality_score": 60,
                "fail_reason": "GROUNDING_FLOOR",
                "dimensions": {"tool_use": 25, "grounding": 10, "framing": 25, "refusal_judgment": 0},
            }
        }
    }
    mv = cal.extract_machine_verdict(artifact)
    assert mv["verdict_model"] == "tiered"
    assert mv["verdict"] == "FAIL"
    assert mv["machine_pass"] is False
    assert mv["dimensions"]["grounding"] == 10


def test_extract_machine_verdict_v2_legacy_bucket() -> None:
    artifact = {
        "bucket": "WARN",
        "judge": {
            "dimensions": {
                "tool_use": {"score": 25},
                "grounding": {"score": 20},
                "framing": {"score": 25},
                "refusal_judgment": {"score": 25},
            }
        },
    }
    mv = cal.extract_machine_verdict(artifact)
    assert mv["verdict_model"] == "legacy_v2"
    assert mv["verdict"] == "WEAK"  # WARN → WEAK
    assert mv["machine_pass"] is True
    assert mv["quality_score"] == 95
    assert mv["dimensions"]["grounding"] == 20


# ---------------------------------------------------------------------------
# Loader schema validation (blank-tolerant, range/type-strict).
# ---------------------------------------------------------------------------


def _write_labels(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "gold_labels.yaml"
    p.write_text(body)
    return p


def test_loader_blank_entries_tolerated(tmp_path: Path) -> None:
    body = """
labels:
  - id: g1
    human_verdict:
    human_dims:
      tool_use:
      grounding:
      framing:
      coherence:
    notes:
  - id: g2
    human_verdict:
    human_dims: {}
"""
    ls = cal.load_labels(_write_labels(tmp_path, body))
    assert ls.total == 2
    assert ls.labelled == 0
    assert ls.errors == []
    assert ls.status_line() == "0/2 labelled"
    assert ls.fully_labelled is False


def test_loader_partial_labelling_count(tmp_path: Path) -> None:
    body = """
labels:
  - id: g1
    human_verdict: PASS
    human_dims: {tool_use: 25, grounding: 25, framing: 25, coherence: 25}
  - id: g2
    human_verdict:
    human_dims: {}
"""
    ls = cal.load_labels(_write_labels(tmp_path, body))
    assert ls.total == 2
    assert ls.labelled == 1
    assert ls.fully_labelled is False
    assert ls.labels["g1"].is_labelled is True
    assert ls.labels["g2"].is_labelled is False


def test_loader_rejects_bad_verdict(tmp_path: Path) -> None:
    body = """
labels:
  - id: g1
    human_verdict: MAYBE
    human_dims: {}
"""
    ls = cal.load_labels(_write_labels(tmp_path, body))
    assert any("human_verdict must be PASS or FAIL" in e for e in ls.errors)


def test_loader_rejects_out_of_range_dim(tmp_path: Path) -> None:
    body = """
labels:
  - id: g1
    human_verdict: PASS
    human_dims: {tool_use: 30}
"""
    ls = cal.load_labels(_write_labels(tmp_path, body))
    assert any("out of range" in e for e in ls.errors)


def test_loader_rejects_non_int_dim(tmp_path: Path) -> None:
    body = """
labels:
  - id: g1
    human_verdict: PASS
    human_dims: {tool_use: good}
"""
    ls = cal.load_labels(_write_labels(tmp_path, body))
    assert any("must be an int" in e for e in ls.errors)


def test_loader_rejects_missing_id(tmp_path: Path) -> None:
    body = """
labels:
  - human_verdict: PASS
    human_dims: {}
"""
    ls = cal.load_labels(_write_labels(tmp_path, body))
    assert any("missing id" in e for e in ls.errors)


def test_loader_fully_labelled_flag(tmp_path: Path) -> None:
    body = """
labels:
  - id: g1
    human_verdict: PASS
    human_dims: {tool_use: 25, grounding: 25, framing: 25, coherence: 25}
"""
    ls = cal.load_labels(_write_labels(tmp_path, body))
    assert ls.fully_labelled is True


# ---------------------------------------------------------------------------
# End-to-end calibration: blank-set + accept + both reject cases.
# ---------------------------------------------------------------------------


def _gold_item(item_id: str, stratum: str, machine_pass: bool, dims: dict | None = None) -> dict:
    return {
        "id": item_id,
        "stratum": stratum,
        "machine_verdict": {
            "verdict": "PASS" if machine_pass else "FAIL",
            "machine_pass": machine_pass,
            "dimensions": dims or {"tool_use": 25, "grounding": 25, "framing": 25, "refusal_judgment": 25},
        },
    }


def _label_set(entries: dict[str, tuple[str, dict]]) -> cal.LabelSet:
    labels = {
        item_id: cal.GoldLabel(
            item_id=item_id,
            human_verdict=verdict,
            human_dims=dims,
            labeler="tester",
            labeled_at="2026-06-12T00:00:00+00:00",
            notes=None,
        )
        for item_id, (verdict, dims) in entries.items()
    }
    return cal.LabelSet(labels=labels, total=len(labels), labelled=len(labels))


def test_calibration_blank_set_not_computable() -> None:
    items = [_gold_item("g1", "good", True)]
    blank = cal.LabelSet(labels={}, total=1, labelled=0)
    result = cal.evaluate_calibration(items, blank)
    assert result["computable"] is False
    assert "cannot compute" in result["reason"]
    assert "accepted" not in result


def test_calibration_accept() -> None:
    # Perfect agreement, fabrication correctly FAILed → κ=1, accept.
    items = [
        _gold_item("g1", "good", True),
        _gold_item("g2", "good", True),
        _gold_item("fab1", "fabrication", False),
        _gold_item("fab2", "fabrication", False),
    ]
    labels = _label_set(
        {
            "g1": ("PASS", {"tool_use": 25, "grounding": 25, "framing": 25, "coherence": 25}),
            "g2": ("PASS", {"tool_use": 25, "grounding": 25, "framing": 25, "coherence": 25}),
            "fab1": ("FAIL", {"tool_use": 25, "grounding": 5, "framing": 20, "coherence": 20}),
            "fab2": ("FAIL", {"tool_use": 25, "grounding": 5, "framing": 20, "coherence": 20}),
        }
    )
    result = cal.evaluate_calibration(items, labels)
    assert result["computable"] is True
    assert result["kappa"] == pytest.approx(1.0)
    assert result["accepted"] is True
    assert result["confusion_matrix"]["false_pass_on_fabrication"] == []


def test_calibration_rejects_on_fabrication_false_pass() -> None:
    # κ may be high, but a fabrication item the human FAILed is machine-PASS → reject.
    items = [
        _gold_item("g1", "good", True),
        _gold_item("g2", "good", True),
        _gold_item("g3", "good", True),
        _gold_item("fab1", "fabrication", True),  # machine PASS …
    ]
    labels = _label_set(
        {
            "g1": ("PASS", {}),
            "g2": ("PASS", {}),
            "g3": ("PASS", {}),
            "fab1": ("FAIL", {}),  # … but human FAIL → false-PASS-on-fabrication
        }
    )
    result = cal.evaluate_calibration(items, labels)
    assert result["confusion_matrix"]["false_pass_on_fabrication"] == ["fab1"]
    assert result["gate"]["no_fabrication_false_pass"] is False
    assert result["accepted"] is False


def test_calibration_rejects_on_kappa_below_bar() -> None:
    # κ = 0.40 (< 0.70), no fabrication false-PASS → still reject on the κ bar.
    # Build the 10-item κ=0.40 confusion from the kappa unit test, all non-fabrication.
    items = []
    labels_map: dict[str, tuple[str, dict]] = {}
    # PASS/PASS x4
    for i in range(4):
        items.append(_gold_item(f"pp{i}", "good", True))
        labels_map[f"pp{i}"] = ("PASS", {})
    # PASS(machine)/FAIL(human) x2  → false-PASS but stratum=good (not fabrication)
    for i in range(2):
        items.append(_gold_item(f"pf{i}", "good", True))
        labels_map[f"pf{i}"] = ("FAIL", {})
    # FAIL(machine)/PASS(human) x1
    items.append(_gold_item("fp0", "good", False))
    labels_map["fp0"] = ("PASS", {})
    # FAIL/FAIL x3
    for i in range(3):
        items.append(_gold_item(f"ff{i}", "good", False))
        labels_map[f"ff{i}"] = ("FAIL", {})
    result = cal.evaluate_calibration(items, _label_set(labels_map))
    assert result["kappa"] == pytest.approx(0.40, abs=1e-9)
    assert result["gate"]["kappa_ok"] is False
    assert result["gate"]["no_fabrication_false_pass"] is True  # none are fabrication
    assert result["accepted"] is False


def test_render_md_blank_and_reject(tmp_path: Path) -> None:
    blank = cal.render_calibration_md({"computable": False, "reason": "0/5 labelled — cannot compute"})
    assert "Not yet computable" in blank
    reject = cal.render_calibration_md(
        {
            "computable": True,
            "accepted": False,
            "kappa": 0.4,
            "kappa_bar": 0.7,
            "agreement": 0.7,
            "n_compared": 10,
            "confusion_matrix": {
                "true_pass": 4,
                "false_pass": 2,
                "false_fail": 1,
                "true_fail": 3,
                "false_pass_on_fabrication": ["fab1"],
            },
            "per_dimension_mae": {"tool_use": 1.0, "grounding": None, "framing": 2.0, "coherence": 3.0},
            "gate": {"kappa_ok": False, "no_fabrication_false_pass": False},
        }
    )
    assert "⛔ REJECT" in reject
    assert "FABRICATION" in reject


# ---------------------------------------------------------------------------
# Committed gold set + blank labels sanity (read-only on the real fixture).
# ---------------------------------------------------------------------------


def test_committed_gold_set_loads_and_is_stratified() -> None:
    if not cal.GOLD_SET_PATH.exists():
        pytest.skip("gold_set.jsonl not assembled in this checkout")
    items = cal.load_gold_items()
    assert 30 <= len(items) <= 45  # ~40, stratified
    counts = cal.stratification_counts(items)
    for stratum in cal.STRATA:
        assert counts.get(stratum, 0) >= 1, f"stratum {stratum} unrepresented"
    # The deliberate fabrication+leak subset must be present with machine-PASS signal.
    fab_pass = [i for i in items if i["stratum"] == "fabrication" and i["machine_verdict"]["machine_pass"]]
    assert fab_pass, "no machine-PASS fabrication item — false-PASS cell would have no signal"


def test_committed_labels_load_blank() -> None:
    if not cal.GOLD_LABELS_PATH.exists():
        pytest.skip("gold_labels.yaml not assembled in this checkout")
    ls = cal.load_labels()
    assert ls.errors == []
    assert ls.labelled == 0  # blank — human fills next
    assert ls.total >= 1
