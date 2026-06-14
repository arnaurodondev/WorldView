"""Offline acceptance check for the learned-router train/serve parity fix (PLAN-0111 #33).

Throwaway diagnostic (not a unit test). For a sample of the 469 shadow docs it:
  1. reproduces the OLD live path (title-only) and confirms it matches the stored
     learned_p_yield (proving the live path had no bug other than the missing lede);
  2. reproduces the NEW fixed path (title + "\n" + subtitle_from_lede(chunk0)) and
     reports the lift + the new proposed-tier distribution.

It loads the SAME committed joblib + meta the container loads, uses the real
EmbeddingGemmaRouterAdapter (DeepInfra) with the key from docker.env, and
concatenates the 3 structured features from feature_scores_json in meta order.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import joblib  # type: ignore[import-untyped]
import numpy as np

_ROOT = Path(__file__).resolve().parents[2]
_MODELS = _ROOT / "services/nlp-pipeline/src/nlp_pipeline/application/blocks/models"

sys.path.insert(0, str(_ROOT / "libs/ml-clients/src"))
from ml_clients.adapters.embeddinggemma_router import EmbeddingGemmaRouterAdapter  # noqa: E402


def _subtitle_from_lede(lede: str | None, max_chars: int = 300) -> str:
    """VERBATIM replica of routing_classifier_dataset._subtitle_from_lede."""
    if not lede:
        return ""
    text = " ".join(lede.split())
    if len(text) <= max_chars:
        return text
    head = text[:max_chars]
    dot = head.rfind(". ")
    return head[: dot + 1] if dot > 60 else head


def _build_text(title: str, subtitle: str) -> str:
    t, s = title.strip(), subtitle.strip()
    return f"{t}\n{s}" if t and s else (t or s)


def _api_key() -> str:
    env = (_ROOT / "services/nlp-pipeline/configs/docker.env").read_text()
    for line in env.splitlines():
        if line.startswith("NLP_PIPELINE_EXTRACTION_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("api key not found")


def _psql(sql: str) -> list[list[str]]:
    out = subprocess.run(
        [
            "docker",
            "exec",
            "worldview-postgres-1",
            "psql",
            "-U",
            "postgres",
            "-d",
            "nlp_db",
            "-t",
            "-A",
            "-F",
            "\x1f",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [ln.split("\x1f") for ln in out.splitlines() if ln.strip()]


def _tier(p: float, thr_e: float, thr_d: float) -> str:
    return "deep" if p >= thr_d else ("medium" if p >= thr_e else "light")


def main(sample: int = 6) -> None:
    meta = json.loads((_MODELS / "routing_classifier_meta.json").read_text())
    model = joblib.load(_MODELS / "routing_classifier.joblib")
    feat_order: list[str] = meta["structured_features"]
    dims: int = meta["embedding_dims"]
    thr_e, thr_d = float(meta["thr_extract"]), float(meta["thr_deep"])

    # Pull shadow docs that have a non-null first chunk + title + features.
    rows = _psql(
        """
        SELECT rd.doc_id::text,
               COALESCE(dsm.title,''),
               round(rd.learned_p_yield::numeric,4),
               rd.feature_scores_json::text,
               (SELECT c.chunk_text FROM chunks c
                 WHERE c.doc_id = rd.doc_id AND c.chunk_text IS NOT NULL
                 ORDER BY c.chunk_index LIMIT 1)
        FROM routing_decisions rd
        LEFT JOIN document_source_metadata dsm ON dsm.doc_id = rd.doc_id
        WHERE rd.learned_tier IS NOT NULL AND rd.processing_path='full_pipeline'
        ORDER BY rd.decided_at DESC;
        """
    )
    embedder = EmbeddingGemmaRouterAdapter(api_key=_api_key())

    def predict(text: str, feats: dict[str, float]) -> float:
        async def _emb() -> list[float]:
            return (await embedder.embed_for_classification([text], dimensions=dims))[0]

        emb = asyncio.get_event_loop().run_until_complete(_emb())
        structured = [float(feats.get(n, 0.0)) for n in feat_order]
        row = np.asarray([structured + list(emb)], dtype=np.float64)
        return float(model.predict_proba(row)[0, 1])

    # --- per-doc parity sample (live title-only must match stored; lede lifts) ---
    print(f"{'doc_id':12} {'stored':>7} {'offl_title':>10} {'+lede':>7}  tier(title->lede)")
    sampled = rows[:sample]
    for doc_id, title, stored, feats_json, lede in sampled:
        feats = json.loads(feats_json)
        stored_p = float(stored)
        p_title = predict(title, feats)
        p_lede = predict(_build_text(title, _subtitle_from_lede(lede)), feats)
        print(
            f"{doc_id[:12]:12} {stored_p:7.4f} {p_title:10.4f} {p_lede:7.4f}  "
            f"{_tier(stored_p, thr_e, thr_d)}->{_tier(p_lede, thr_e, thr_d)}  "
            f"(match_title_only={abs(p_title - stored_p) < 0.01})"
        )

    # --- full-sample new proposed-tier distribution (with lede) ---
    print("\nNew proposed-tier distribution (title+lede) over", len(rows), "docs:")
    dist = {"deep": 0, "medium": 0, "light": 0}
    for _doc_id, title, _stored, feats_json, lede in rows:
        feats = json.loads(feats_json)
        p_lede = predict(_build_text(title, _subtitle_from_lede(lede)), feats)
        dist[_tier(p_lede, thr_e, thr_d)] += 1
    n = sum(dist.values()) or 1
    for k in ("deep", "medium", "light"):
        print(f"  {k:7}: {dist[k]:4} ({100 * dist[k] / n:.1f}%)")


if __name__ == "__main__":
    asyncio.set_event_loop(asyncio.new_event_loop())
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 6)
