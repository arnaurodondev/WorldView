"""GLiNER local adapter — NER via locally loaded GLiNER model."""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from ml_clients.dataclasses import EntityMention, NERInput, NEROutput
from ml_clients.errors import FatalError, RetryableError

logger = structlog.get_logger()

try:
    from gliner import GLiNER as _GLiNER

    _GLINER_AVAILABLE = True
except ImportError:
    _GLiNER = None
    _GLINER_AVAILABLE = False


def _compute_iou(start_a: int, end_a: int, start_b: int, end_b: int) -> float:
    """Compute Intersection over Union for two text spans."""
    intersection = max(0, min(end_a, end_b) - max(start_a, start_b))
    union = (end_a - start_a) + (end_b - start_b) - intersection
    return intersection / union if union > 0 else 0.0


def _apply_nms(entities: list[dict[str, Any]], iou_threshold: float = 0.5) -> list[dict[str, Any]]:
    """Non-maximum suppression: keep highest-scored span, discard overlapping spans."""
    sorted_entities = sorted(entities, key=lambda e: float(e["score"]), reverse=True)
    kept: list[dict[str, Any]] = []
    for entity in sorted_entities:
        overlaps = any(_compute_iou(entity["start"], entity["end"], k["start"], k["end"]) > iou_threshold for k in kept)
        if not overlaps:
            kept.append(entity)
    return kept


class GLiNERLocalAdapter:
    """Implements NERClient using a locally loaded GLiNER model.

    The model is loaded lazily on first call (thread-safe via asyncio.Lock).
    All synchronous GLiNER calls are offloaded to a thread executor to avoid
    blocking the event loop.
    """

    def __init__(self, model_path: str, semaphore: asyncio.Semaphore) -> None:
        self._model_path = model_path
        self._semaphore = semaphore
        self._model: Any = None
        self._model_lock = asyncio.Lock()

    async def _get_model(self) -> Any:
        if self._model is None:
            async with self._model_lock:
                if self._model is None:
                    if not _GLINER_AVAILABLE or _GLiNER is None:
                        raise FatalError("gliner package not installed; install ml-clients[gliner]")
                    loop = asyncio.get_event_loop()
                    model_path = self._model_path
                    self._model = await loop.run_in_executor(None, lambda: _GLiNER.from_pretrained(model_path))
        return self._model

    async def extract_entities(self, inp: NERInput) -> NEROutput:
        results = await self.batch_extract_entities([inp])
        return results[0]

    async def batch_extract_entities(self, inputs: list[NERInput]) -> list[NEROutput]:
        """Run GLiNER on a batch of texts in a single model forward pass.

        GLiNER accepts a list of texts natively — one GPU/CPU forward pass for
        all sections rather than N separate calls.  All inputs must use the same
        entity_classes and threshold; if they differ, the first input's values are
        used (documents are always processed with a single ontology in this system).

        NMS is applied per-section so overlapping spans within a single section are
        suppressed without affecting other sections in the batch.
        """
        if not inputs:
            return []
        async with self._semaphore:
            try:
                model = await self._get_model()
                loop = asyncio.get_event_loop()

                texts = [inp.text for inp in inputs]
                entity_classes = inputs[0].entity_classes
                threshold = inputs[0].threshold

                def sync_batch_call() -> list[list[dict[str, Any]]]:
                    # GLiNER predict_entities(list, labels) silently returns [] — the
                    # batch API is broken (BP-123). Must iterate individually like server.py.
                    return [  # type: ignore[no-any-return]
                        model.predict_entities(t, entity_classes, threshold=threshold) for t in texts
                    ]

                raw_batched: list[list[dict[str, Any]]] = await loop.run_in_executor(None, sync_batch_call)

                outputs: list[NEROutput] = []
                for raw_entities in raw_batched:
                    filtered = _apply_nms(raw_entities)
                    mentions = [
                        EntityMention(
                            text=str(e["text"]),
                            label=str(e["label"]),
                            start=int(e["start"]),
                            end=int(e["end"]),
                            score=float(e["score"]),
                        )
                        for e in filtered
                    ]
                    outputs.append(NEROutput(mentions=mentions))

                logger.info(
                    "ner_batch_completed",
                    model_path=self._model_path,
                    batch_size=len(inputs),
                    total_entities=sum(len(o.mentions) for o in outputs),
                )
                return outputs
            except (MemoryError, RuntimeError) as exc:
                raise RetryableError(f"GLiNER transient error: {exc}") from exc
            except ValueError as exc:
                raise FatalError(f"GLiNER input error: {exc}") from exc
            except (RetryableError, FatalError):
                raise
            except Exception as exc:
                raise FatalError(f"Unexpected NER error: {exc}") from exc
