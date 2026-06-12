"""Offline tests for the routing-classifier dataset builder (PLAN-0111 C-3).

These exercise the pure logic (URL normalisation, subtitle derivation, cost
estimation, CSV serialisation) WITHOUT any DB or network. The DB-bound functions
(build_rows / load_yield_counts) are integration-tested manually against the live
DBs; their SQL is documented in the module docstring.

Run:  python -m pytest scripts/eval/test_routing_classifier_dataset.py -v
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import routing_classifier_dataset as rcd

# ── URL normalisation ─────────────────────────────────────────────────────────


def test_normalize_sync_url_strips_async_drivers() -> None:
    assert rcd._normalize_sync_url("postgresql+asyncpg://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"
    assert rcd._normalize_sync_url("postgresql+psycopg://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"
    # plain URLs pass through untouched
    assert rcd._normalize_sync_url("postgresql://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"


def test_db_url_prefers_test_var(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("NLP_DB_URL_TEST", "postgresql+asyncpg://t/db")
    monkeypatch.setenv("NLP_DB_URL", "postgresql://prod/db")
    assert rcd._db_url("NLP_DB_URL_TEST", "NLP_DB_URL") == "postgresql://t/db"
    monkeypatch.delenv("NLP_DB_URL_TEST")
    assert rcd._db_url("NLP_DB_URL_TEST", "NLP_DB_URL") == "postgresql://prod/db"
    monkeypatch.delenv("NLP_DB_URL")
    assert rcd._db_url("NLP_DB_URL_TEST", "NLP_DB_URL") is None


# ── subtitle / lede derivation ─────────────────────────────────────────────────


def test_subtitle_from_lede_empty() -> None:
    assert rcd._subtitle_from_lede(None) == ""
    assert rcd._subtitle_from_lede("") == ""


def test_subtitle_from_lede_collapses_whitespace() -> None:
    assert rcd._subtitle_from_lede("  Apple   beats\n\nestimates  ") == "Apple beats estimates"


def test_subtitle_from_lede_truncates_at_sentence_boundary() -> None:
    long = "First sentence is reasonably long and informative for the lede. " + ("x" * 400)
    out = rcd._subtitle_from_lede(long, max_chars=80)
    # should cut at the sentence boundary (the ". ") rather than mid-word
    assert out.endswith(".")
    assert len(out) <= 80


def test_subtitle_from_lede_hard_cut_when_no_boundary() -> None:
    long = "x" * 500
    out = rcd._subtitle_from_lede(long, max_chars=100)
    assert len(out) == 100


# ── cost estimation ────────────────────────────────────────────────────────────


def test_estimate_light_cost_scales_with_sample_size() -> None:
    small = rcd.estimate_light_cost(avg_words=500, sample_size=100)
    big = rcd.estimate_light_cost(avg_words=500, sample_size=400)
    assert big["est_usd_worst_case"] > small["est_usd_worst_case"]
    # 4x the docs ≈ 4x the cost (linear; tolerance covers 4-dp rounding in the est)
    assert abs(big["est_usd_worst_case"] - 4 * small["est_usd_worst_case"]) < 1e-3
    assert big["sample_size"] == 400
    assert big["rate_in_per_1m_usd"] == rcd._EXTRACT_IN_PER_M


def test_estimate_light_cost_token_math() -> None:
    est = rcd.estimate_light_cost(avg_words=500, sample_size=1)
    # input = (500 words + 1500 overhead) * 1.3 = 2600 tokens
    assert est["est_input_tokens"] == int((500 + 1500) * 1.3)
    assert est["est_output_tokens_worst_case"] == rcd._EXTRACT_MAX_OUT_TOKENS


# ── CSV serialisation ──────────────────────────────────────────────────────────


def _row(doc_id: str = "d1", yielded: bool = True) -> rcd.DatasetRow:
    return rcd.DatasetRow(
        doc_id=doc_id,
        title="Acme beats Q3",
        subtitle="Acme Corp reported strong results.",
        entity_density=0.4,
        source_reliability=0.5,
        recency=0.9,
        document_type=0.55,
        extraction_yield=0.23,
        routed_tier="deep",
        n_relations=3,
        n_claims=1,
        n_events=2,
        yielded=yielded,
        degraded=False,
    )


def test_write_csv_roundtrip(tmp_path: Path) -> None:
    rows = [_row("d1", True), _row("d2", False)]
    out = tmp_path / "ds.csv"
    rcd.write_csv(out, rows)
    with out.open(encoding="utf-8") as fh:
        read = list(csv.DictReader(fh))
    assert len(read) == 2
    assert read[0]["doc_id"] == "d1"
    assert read[0]["yielded"] == "True"
    assert read[1]["yielded"] == "False"
    assert read[0]["n_relations"] == "3"
    # header carries the leakage-suspect feature so downstream can drop it
    assert "extraction_yield" in read[0]


def test_live_features_exclude_dead_signals() -> None:
    # the 3 dead signals must NOT be in the live feature set
    for dead in ("novelty", "watchlist", "price_impact"):
        assert dead not in rcd._LIVE_FEATURES
    assert rcd._LEAKAGE_SUSPECT_FEATURE in rcd._LIVE_FEATURES
