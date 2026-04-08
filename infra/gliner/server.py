"""GLiNER HTTP server — exposes batch NER inference over a REST API.

Decouples the NLP pipeline from in-process GLiNER, allowing:
  - Independent container scaling
  - GPU allocation to a dedicated pod
  - Warm model across multiple NLP pipeline replicas

Routes
------
POST /ner          — single-text inference (kept for compatibility)
POST /ner/batch    — batch inference (list of texts, one forward pass)
GET  /healthz      — liveness probe
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

# ── Model load ────────────────────────────────────────────────────────────────

_model: Any = None
_model_lock = asyncio.Lock()
_MODEL_PATH = os.environ.get("GLINER_MODEL_PATH", "urchade/gliner_large-v2.1")


async def _get_model() -> Any:
    global _model
    if _model is None:
        async with _model_lock:
            if _model is None:
                from gliner import GLiNER  # type: ignore[import-not-found]

                loop = asyncio.get_event_loop()
                _model = await loop.run_in_executor(None, lambda: GLiNER.from_pretrained(_MODEL_PATH))
    return _model


# ── Schemas ───────────────────────────────────────────────────────────────────


class NERRequest(BaseModel):
    text: str
    entity_classes: list[str]
    threshold: float = 0.35


class BatchNERRequest(BaseModel):
    texts: list[str]
    entity_classes: list[str]
    threshold: float = 0.35


class EntitySpan(BaseModel):
    text: str
    label: str
    start: int
    end: int
    score: float


class NERResponse(BaseModel):
    entities: list[EntitySpan]


class BatchNERResponse(BaseModel):
    results: list[list[EntitySpan]]


# ── App ───────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    """Pre-load the model at startup so the first request is fast."""
    await _get_model()
    yield


app = FastAPI(title="GLiNER Server", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ner", response_model=NERResponse)
async def ner_single(req: NERRequest) -> NERResponse:
    """Single-text NER (convenience wrapper over batch)."""
    batch_resp = await ner_batch(
        BatchNERRequest(
            texts=[req.text],
            entity_classes=req.entity_classes,
            threshold=req.threshold,
        )
    )
    return NERResponse(entities=batch_resp.results[0] if batch_resp.results else [])


@app.post("/ner/batch", response_model=BatchNERResponse)
async def ner_batch(req: BatchNERRequest) -> BatchNERResponse:
    """Batch NER — processes each text individually (GLiNER predict_entities
    does not support list input reliably across versions)."""
    if not req.texts:
        return BatchNERResponse(results=[])

    model = await _get_model()
    loop = asyncio.get_event_loop()

    def _run_batch() -> list[list[dict[str, Any]]]:
        return [model.predict_entities(text, req.entity_classes, threshold=req.threshold) for text in req.texts]

    raw_batched: list[list[dict[str, Any]]] = await loop.run_in_executor(None, _run_batch)

    results: list[list[EntitySpan]] = [
        [
            EntitySpan(
                text=str(e["text"]),
                label=str(e["label"]),
                start=int(e["start"]),
                end=int(e["end"]),
                score=float(e["score"]),
            )
            for e in section_entities
        ]
        for section_entities in raw_batched
    ]
    return BatchNERResponse(results=results)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)  # noqa: S104
