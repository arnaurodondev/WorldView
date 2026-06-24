"""Offline tests for the extraction-quality eval harness.

These exercise the harness's pure logic end-to-end WITHOUT any DB or network:
prompt rendering (against the real DEEP_EXTRACTION template), model-output
parsing, the judge flow (with the HTTP layer monkeypatched), aggregation, the
report verdict, the self-preference guard, and cost estimation.

Run:  python -m pytest scripts/eval/test_extraction_quality_eval.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parent))

import extraction_quality_eval as eqe

if TYPE_CHECKING:
    import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _article(doc_id: str = "doc-1", bucket: str = "earnings", text: str | None = None) -> eqe.GoldenArticle:
    return eqe.GoldenArticle(
        doc_id=doc_id,
        title="Acme beats Q3 estimates",
        source_name="Reuters",
        published_at="2026-01-15T00:00:00+00:00",
        routing_tier="DEEP",
        span_bucket=bucket,
        word_count=120,
        entity_count=2,
        entities="Acme Corp, Jane Smith",
        text=text or "Acme Corp reported revenue of $5B on 2026-01-15. Jane Smith is CEO of Acme Corp.",
    )


_GOOD_OUTPUT = {
    "events": [
        {
            "event_type": "EARNINGS_RELEASE",
            "description": "Acme Q3 results",
            "entity_refs": ["Acme Corp"],
            "valid_from": "2026-01-15",
            "valid_to": None,
            "confidence": 0.95,
        },
    ],
    "claims": [
        {
            "entity_ref": "Acme Corp",
            "claim_type": "REVENUE_GROWTH",
            "polarity": "positive",
            "confidence": 0.9,
            "evidence_text": "reported revenue of $5B",
        },
    ],
    "relations": [
        {
            "subject_ref": "Acme Corp",
            "predicate": "has_executive",
            "object_ref": "Jane Smith",
            "confidence": 0.97,
            "evidence_text": "Jane Smith is CEO of Acme Corp",
        },
    ],
}


# ── Prompt rendering (uses the REAL libs/prompts template) ───────────────────


def test_render_prompt_uses_real_template() -> None:
    eqe._ensure_prompts_importable()
    prompt = eqe._render_extraction_prompt("Acme Corp, Jane Smith", "Acme Corp reported revenue.")
    # The allow-list and text are filled in; the controlled-vocab block is present.
    assert "Acme Corp, Jane Smith" in prompt
    assert "Acme Corp reported revenue." in prompt
    assert "has_executive" in prompt  # predicate vocabulary from the real prompt
    assert "FABRICATION IS PROHIBITED" in prompt


# ── Output parsing ────────────────────────────────────────────────────────────


def test_run_parses_good_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_chat(*a, **k):
        return json.dumps(_GOOD_OUTPUT), 1500, 200

    monkeypatch.setattr(eqe, "_deepinfra_chat", fake_chat)
    r = eqe.run_model_on_article(object(), "k", "url", "model-x", _article())
    assert r.status == "ok"
    assert (r.n_events, r.n_claims, r.n_relations) == (1, 1, 1)
    assert r.parsed == _GOOD_OUTPUT


def test_run_handles_json_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_chat(*a, **k):
        return "```json\n" + json.dumps(_GOOD_OUTPUT) + "\n```", 1, 1

    monkeypatch.setattr(eqe, "_deepinfra_chat", fake_chat)
    r = eqe.run_model_on_article(object(), "k", "url", "model-x", _article())
    assert r.status == "ok" and r.parsed is not None


def test_run_records_json_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eqe, "_deepinfra_chat", lambda *a, **k: ("not json at all", 1, 1))
    r = eqe.run_model_on_article(object(), "k", "url", "model-x", _article())
    assert r.status == "json_error" and r.parsed is None


def test_run_records_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a, **k):
        raise RuntimeError("503 upstream")

    monkeypatch.setattr(eqe, "_deepinfra_chat", boom)
    r = eqe.run_model_on_article(object(), "k", "url", "model-x", _article())
    assert r.status == "api_error" and "503" in (r.error or "")


# ── Arm parsing (model@reasoning_effort) ─────────────────────────────────────


def test_parse_arm_with_effort_suffix() -> None:
    # An "@effort" suffix selects a per-arm reasoning setting; the arm_id keeps the
    # full spec so the same physical model at two settings stays distinct downstream.
    physical, effort, arm_id = eqe._parse_arm("Qwen/Qwen3-235B-A22B-Instruct-2507@low")
    assert physical == "Qwen/Qwen3-235B-A22B-Instruct-2507"
    assert effort == "low"
    assert arm_id == "Qwen/Qwen3-235B-A22B-Instruct-2507@low"


def test_parse_arm_without_suffix_uses_default() -> None:
    physical, effort, arm_id = eqe._parse_arm("openai/gpt-oss-120b")
    assert physical == "openai/gpt-oss-120b"
    assert effort == eqe._EXTRACTION_REASONING_EFFORT  # module default
    assert arm_id == "openai/gpt-oss-120b"


def test_run_arm_id_distinguishes_same_model(monkeypatch: pytest.MonkeyPatch) -> None:
    # Two arms of one physical model must yield distinct ModelRunResult.model_id so
    # aggregation/report treat them as separate rows.
    captured: list[str] = []

    def fake_chat(client, key, url, model, **k):
        captured.append(f"{model}|{k.get('reasoning_effort')}")
        return json.dumps(_GOOD_OUTPUT), 1, 1

    monkeypatch.setattr(eqe, "_deepinfra_chat", fake_chat)
    r_low = eqe.run_model_on_article(object(), "k", "url", "mdl@low", _article())
    r_none = eqe.run_model_on_article(object(), "k", "url", "mdl@none", _article())
    assert r_low.model_id == "mdl@low" and r_none.model_id == "mdl@none"
    # The HTTP call used the stripped physical model + the arm's effort.
    assert captured == ["mdl|low", "mdl|none"]


# ── Judge flow ────────────────────────────────────────────────────────────────


def _ok_run(model_id: str, parsed: dict | None = None) -> eqe.ModelRunResult:
    parsed = parsed if parsed is not None else _GOOD_OUTPUT
    return eqe.ModelRunResult(
        doc_id="doc-1",
        model_id=model_id,
        status="ok",
        latency_s=2.0,
        tokens_in=1500,
        tokens_out=200,
        raw_response=json.dumps(parsed),
        parsed=parsed,
        error=None,
        n_events=len(parsed["events"]),
        n_claims=len(parsed["claims"]),
        n_relations=len(parsed["relations"]),
    )


def test_judge_deepinfra_path(monkeypatch: pytest.MonkeyPatch) -> None:
    verdict = {
        "precision": 5,
        "recall": 4,
        "adherence": 5,
        "fabricated_items": 0,
        "allowlist_violations": 0,
        "missed_items": 1,
        "justification": "faithful",
    }
    monkeypatch.setattr(eqe, "_deepinfra_chat", lambda *a, **k: (json.dumps(verdict), 800, 120))
    s = eqe.judge_extraction(
        None,
        None,
        object(),
        "dkey",
        eqe._PROD_EXTRACTION_MODEL,
        _article(),
        _ok_run("deepseek-ai/DeepSeek-V4-Flash"),
    )
    assert s.status == "ok"
    assert (s.precision, s.recall, s.adherence) == (5, 4, 5)
    assert s.judge_model == eqe._PROD_EXTRACTION_MODEL  # independent of the candidate


def test_judge_anthropic_path(monkeypatch: pytest.MonkeyPatch) -> None:
    verdict = {
        "precision": 4,
        "recall": 4,
        "adherence": 4,
        "fabricated_items": 0,
        "allowlist_violations": 0,
        "missed_items": 0,
        "justification": "ok",
    }
    monkeypatch.setattr(eqe, "_call_anthropic_judge", lambda *a, **k: json.dumps(verdict))
    s = eqe.judge_extraction(
        object(),
        "akey",
        None,
        None,
        eqe._PROD_EXTRACTION_MODEL,
        _article(),
        _ok_run(eqe._PROD_EXTRACTION_MODEL),  # judging the 235B itself
    )
    # Anthropic judge is independent of ALL DeepInfra candidates, incl. the 235B.
    assert s.status == "ok" and s.judge_model == eqe._ANTHROPIC_JUDGE_MODEL


def test_judge_self_preference_guard() -> None:
    # DeepInfra fallback judge == the 235B candidate → must refuse to self-grade.
    s = eqe.judge_extraction(
        None,
        None,
        object(),
        "dkey",
        eqe._PROD_EXTRACTION_MODEL,
        _article(),
        _ok_run(eqe._PROD_EXTRACTION_MODEL),
    )
    assert s.status == "judge_error" and "self-grade" in (s.error or "")


def test_judge_floors_unparseable_output() -> None:
    bad_run = eqe.ModelRunResult(
        doc_id="doc-1",
        model_id="m",
        status="json_error",
        latency_s=1.0,
        tokens_in=1,
        tokens_out=1,
        raw_response="garbage",
        parsed=None,
        error="JSONDecodeError",
    )
    s = eqe.judge_extraction(None, None, object(), "dkey", "other-judge", _article(), bad_run)
    assert s.status == "skipped_unparseable_output"
    assert (s.precision, s.recall, s.adherence) == (1, 1, 1)  # floor, no judge call


# ── Aggregation + report ──────────────────────────────────────────────────────


def test_aggregate_and_report() -> None:
    base, cand = eqe._PROD_EXTRACTION_MODEL, "deepseek-ai/DeepSeek-V4-Flash"
    runs = [_ok_run(base), _ok_run(cand)]
    scores = [
        eqe.JudgeScore("doc-1", base, "judge", "ok", 5, 5, 5, 0, 0, 0, "great"),
        eqe.JudgeScore("doc-1", cand, "judge", "ok", 3, 3, 3, 2, 1, 2, "weaker"),
    ]
    aggs = eqe.aggregate(runs, scores, [base, cand])
    by_model = {a.model_id: a for a in aggs}
    assert by_model[base].mean_overall == 5.0
    assert by_model[cand].mean_overall == 3.0
    assert by_model[cand].fabrication_rate == 2.0  # 2 fabricated / 1 article

    report = eqe.build_report_md(aggs, baseline=base)
    assert "Ranked verdict" in report
    assert "BELOW baseline" in report  # 3.0 vs 5.0 → below tolerance


def test_report_matches_verdict_within_tolerance() -> None:
    # 4 articles: candidate ties on 3 and drops one dimension on the 4th, so its
    # overall (~4.917) is within the -0.10 tolerance of baseline (5.0).
    base, cand = eqe._PROD_EXTRACTION_MODEL, "cand"
    runs = [_ok_run(base) for _ in range(4)] + [_ok_run(cand) for _ in range(4)]
    scores = []
    for i in range(4):
        scores.append(eqe.JudgeScore(f"doc-{i}", base, "j", "ok", 5, 5, 5, 0, 0, 0, ""))
    for i in range(4):
        adh = 4 if i == 3 else 5  # one article: adherence 4 → overall 4.667 for that doc
        scores.append(eqe.JudgeScore(f"doc-{i}", cand, "j", "ok", 5, 5, adh, 0, 0, 0, ""))
    aggs = eqe.aggregate(runs, scores, [base, cand])
    report = eqe.build_report_md(aggs, baseline=base)
    assert "MATCHES baseline" in report  # Δ ≈ -0.083, within the -0.10 tolerance


# ── Cost estimation + spot-check ──────────────────────────────────────────────


def test_estimate_cost_runs() -> None:
    arts = [_article(f"d{i}") for i in range(5)]
    text = eqe.estimate_cost(arts, ["m1", "m2"])
    assert "Cost estimate for 5 articles" in text
    assert "TOTAL" in text


def test_human_spotcheck_renders() -> None:
    arts = [_article("d1"), _article("d2", bucket="thin")]
    runs = [_ok_run("m1"), eqe.ModelRunResult("d1", "m1", "ok", 1.0, 1, 1, "{}", _GOOD_OUTPUT, None, 1, 1, 1)]
    md = eqe.build_human_spotcheck(arts, runs, ["m1"], n=2)
    assert "Human spot-check sheet" in md
    assert "d1" in md
