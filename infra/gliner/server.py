"""GLiNER HTTP server — exposes batch NER inference over a REST API.

Decouples the NLP pipeline from in-process GLiNER, allowing:
  - Independent container scaling
  - GPU allocation to a dedicated pod
  - Warm model across multiple NLP pipeline replicas

Server-side micro-batching
--------------------------
The article-consumer fleet (3 replicas x 16 concurrency = ~48 concurrent
single-text /ner requests) would otherwise drive ~48 *independent* forward
passes through a GIL-serial model — i.e. effectively batch-1 throughput.

To exploit GLiNER's ``batch_predict_entities`` (which runs one padded forward
pass over N texts and is ~13.7x faster at N=16 vs N=1), we interpose a single
in-process micro-batch queue between the HTTP handlers and the model:

  request --> Future + enqueue(text, labels, threshold) --> await Future
                                                              ^
  collector loop: drain up to GLINER_MAX_BATCH items that SHARE the same
  (entity_classes, threshold) key, OR until GLINER_BATCH_WAIT_MS elapses since
  the first item; run ONE batch_predict_entities per group; resolve each
  Future with its slice.

The external HTTP contract is unchanged — callers still send single-text /ner
or multi-text /ner/batch and get the same per-text response shape.

Why group by (labels, threshold): ``batch_predict_entities`` applies a single
label set + threshold to every text in the batch, so we can only co-batch
requests that agree on both. In practice the article-consumer uses one fixed
label set + threshold, so virtually everything co-batches; but mixed callers
are handled correctly by bucketing into per-key sub-batches.

Routes
------
POST /ner          — single-text inference (kept for compatibility)
POST /ner/batch    — batch inference (list of texts, one forward pass)
GET  /healthz      — liveness probe
GET  /metrics      — Prometheus exposition (batch-size histogram)
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Response
from pydantic import BaseModel


def _log(event: str, **fields: Any) -> None:
    """Minimal structured (JSON-line) logger — avoids pulling structlog into the
    lean GLiNER image while keeping logs grep-friendly (event= key=value)."""
    rec = {"event": event, **fields}
    print(json.dumps(rec, default=str), file=sys.stdout, flush=True)  # noqa: T201


# ── Config ────────────────────────────────────────────────────────────────────

# CPU-bottleneck fix (2026-06-21): cap the PyTorch intra-op thread pool to the
# container's CPU quota (TORCH_NUM_THREADS, default 4). PyTorch otherwise defaults
# to one OpenMP thread per HOST core (14 here) while the container is capped at 4
# CPUs — 14 threads on a 4-core CFS quota thrash/throttle, so inference used only
# ~12% CPU and a single article took >300s. The OMP_/MKL_ env vars (set in compose)
# cover the BLAS pools; this pins torch's own intra-op pool explicitly and early,
# before the model loads. No effect on output, only on threading efficiency.
try:
    import torch as _torch

    _torch.set_num_threads(int(os.environ.get("TORCH_NUM_THREADS", "4")))
except Exception:  # noqa: S110 — best-effort thread tuning must never break startup
    pass

_MODEL_PATH = os.environ.get("GLINER_MODEL_PATH", "urchade/gliner_large-v2.1")

# Dual-trigger micro-batch knobs (overridable via compose env).
#   GLINER_MAX_BATCH    — cap on texts per forward pass. Throughput peaks at 16
#                         (13.7x vs batch-1) and DEGRADES beyond (32 is slower),
#                         so 16 is the knee. Do not raise without re-running the
#                         batch-size sweep.
#   GLINER_BATCH_WAIT_MS— max time the collector waits to fill a batch after the
#                         first item arrives. 25ms trades a tiny tail-latency
#                         add for near-full batches under the ~48-concurrent load.
GLINER_MAX_BATCH = int(os.environ.get("GLINER_MAX_BATCH", "16"))
GLINER_BATCH_WAIT_MS = float(os.environ.get("GLINER_BATCH_WAIT_MS", "25"))

# ── Metrics ───────────────────────────────────────────────────────────────────

# Lightweight in-process metrics (no prometheus_client dependency). Buckets
# straddle the 16 knee so we can confirm batches actually fill under load.
_BATCH_BUCKETS = (1, 2, 4, 8, 12, 16, 24, 32)
_METRICS: dict[str, Any] = {
    "flushed_total": 0,
    "errors_total": 0,
    "batch_size_sum": 0,
    "batch_size_count": 0,
    "batch_size_buckets": dict.fromkeys(_BATCH_BUCKETS, 0),
}


def _observe_batch_size(n: int) -> None:
    _METRICS["batch_size_sum"] += n
    _METRICS["batch_size_count"] += 1
    for b in _BATCH_BUCKETS:
        if n <= b:
            _METRICS["batch_size_buckets"][b] += 1


def _render_metrics() -> str:
    lines = [
        f"gliner_micro_batch_flushed_total {_METRICS['flushed_total']}",
        f"gliner_micro_batch_errors_total {_METRICS['errors_total']}",
        f"gliner_batch_size_sum {_METRICS['batch_size_sum']}",
        f"gliner_batch_size_count {_METRICS['batch_size_count']}",
    ]
    for b, c in _METRICS["batch_size_buckets"].items():
        lines.append(f'gliner_batch_size_bucket{{le="{b}"}} {c}')
    return "\n".join(lines) + "\n"


# ── Model load ────────────────────────────────────────────────────────────────

_model: Any = None
_model_lock = asyncio.Lock()


async def _get_model() -> Any:
    global _model
    if _model is None:
        async with _model_lock:
            if _model is None:
                from gliner import GLiNER  # type: ignore[import-not-found]

                loop = asyncio.get_event_loop()
                _model = await loop.run_in_executor(None, lambda: GLiNER.from_pretrained(_MODEL_PATH))
    return _model


# ── Micro-batch queue ──────────────────────────────────────────────────────────


class _QueueItem:
    """One pending single-text NER request awaiting batched inference."""

    __slots__ = ("text", "labels", "threshold", "future")

    def __init__(self, text: str, labels: list[str], threshold: float, future: asyncio.Future[list[dict[str, Any]]]):
        self.text = text
        self.labels = labels
        self.threshold = threshold
        self.future = future


def _group_key(labels: list[str], threshold: float) -> tuple[tuple[str, ...], float]:
    """Co-batchable iff (label set, threshold) match. Order of labels is
    preserved (callers send a stable list); we use the tuple directly so two
    requests with differently-ordered labels are *not* merged — safest default
    since GLiNER output offsets/labels are tied to the exact label list."""
    return (tuple(labels), threshold)


# Bounded queue: backpressure if the collector ever falls behind (it shouldn't —
# one forward pass at a time is the model's natural rate limiter).
_queue: asyncio.Queue[_QueueItem] = asyncio.Queue(maxsize=4096)
_collector_task: asyncio.Task[None] | None = None


def _predict_batch(model: Any, texts: list[str], labels: list[str], threshold: float) -> list[list[dict[str, Any]]]:
    """One padded forward pass over N texts sharing (labels, threshold)."""
    return model.batch_predict_entities(texts, labels, threshold=threshold)  # type: ignore[no-any-return]


async def _flush_group(model: Any, loop: asyncio.AbstractEventLoop, items: list[_QueueItem], wait_ms: float) -> None:
    """Run ONE batched forward pass for a group of same-key items and resolve
    each Future with its slice. Errors fail only this group's Futures."""
    texts = [it.text for it in items]
    labels = items[0].labels
    threshold = items[0].threshold
    key_hash = hashlib.sha1(  # noqa: S324 — non-crypto, just a short stable group id for logs
        json.dumps([labels, threshold], sort_keys=True).encode()
    ).hexdigest()[:8]
    try:
        # batch_predict_entities is correct for N>=1 (single-item batch is not
        # slower than predict_entities and yields identical spans — verified).
        results = await loop.run_in_executor(None, _predict_batch, model, texts, labels, threshold)
        for it, res in zip(items, results, strict=True):
            if not it.future.done():
                it.future.set_result(res)
    except Exception as exc:  # — isolate: fail only this group, keep collector alive
        _METRICS["errors_total"] += 1
        _log("gliner_micro_batch_failed", batch_size=len(items), group_key_hash=key_hash, error=str(exc))
        for it in items:
            if not it.future.done():
                it.future.set_exception(exc)
        return
    _METRICS["flushed_total"] += 1
    _observe_batch_size(len(items))
    _log(
        "gliner_micro_batch_flushed",
        batch_size=len(items),
        wait_ms=round(wait_ms, 2),
        group_key_hash=key_hash,
    )


async def _collector() -> None:
    """Single background coroutine: dual-trigger batching.

    Loop: block for the first item, then drain up to GLINER_MAX_BATCH items
    SHARING the first item's (labels, threshold) key OR until
    GLINER_BATCH_WAIT_MS elapses. Items with a different key seen during the
    window are deferred (left on a holding buffer) and processed next loop —
    they form their own sub-batch. Run one forward pass for the chosen group.
    """
    model = await _get_model()
    loop = asyncio.get_event_loop()
    deferred: list[_QueueItem] = []
    while True:
        try:
            # Take the seed item: prefer anything deferred from the prior loop,
            # else block on the queue.
            if deferred:
                first = deferred.pop(0)
            else:
                first = await _queue.get()

            key = _group_key(first.labels, first.threshold)
            group: list[_QueueItem] = [first]
            deadline = time.monotonic() + GLINER_BATCH_WAIT_MS / 1000.0

            # Re-scan deferred buffer for same-key items first (no waiting).
            still_deferred: list[_QueueItem] = []
            for it in deferred:
                if len(group) < GLINER_MAX_BATCH and _group_key(it.labels, it.threshold) == key:
                    group.append(it)
                else:
                    still_deferred.append(it)
            deferred = still_deferred

            # Drain fresh arrivals until full or the wait window expires.
            while len(group) < GLINER_MAX_BATCH:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    nxt = await asyncio.wait_for(_queue.get(), timeout=remaining)
                except TimeoutError:
                    break
                if _group_key(nxt.labels, nxt.threshold) == key:
                    group.append(nxt)
                else:
                    # Different key — defer for a subsequent loop (its own batch).
                    deferred.append(nxt)

            elapsed_ms = (GLINER_BATCH_WAIT_MS / 1000.0 - max(0.0, deadline - time.monotonic())) * 1000.0
            await _flush_group(model, loop, group, elapsed_ms)
        except asyncio.CancelledError:  # graceful shutdown
            raise
        except Exception as exc:  # — collector must never die
            _log("gliner_collector_loop_error", error=str(exc))
            await asyncio.sleep(0.01)


async def _submit(text: str, labels: list[str], threshold: float) -> list[dict[str, Any]]:
    """Enqueue one text and await its batched result."""
    loop = asyncio.get_event_loop()
    future: asyncio.Future[list[dict[str, Any]]] = loop.create_future()
    await _queue.put(_QueueItem(text, labels, threshold, future))
    return await future


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
    """Pre-load the model and start the micro-batch collector at startup."""
    global _collector_task
    await _get_model()
    _collector_task = asyncio.create_task(_collector())
    _log("gliner_started", max_batch=GLINER_MAX_BATCH, batch_wait_ms=GLINER_BATCH_WAIT_MS)
    try:
        yield
    finally:
        if _collector_task is not None:
            _collector_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await _collector_task


app = FastAPI(title="GLiNER Server", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=_render_metrics(), media_type="text/plain; version=0.0.4")


def _to_spans(raw: list[dict[str, Any]]) -> list[EntitySpan]:
    return [
        EntitySpan(
            text=str(e["text"]),
            label=str(e["label"]),
            start=int(e["start"]),
            end=int(e["end"]),
            score=float(e["score"]),
        )
        for e in raw
    ]


@app.post("/ner", response_model=NERResponse)
async def ner_single(req: NERRequest) -> NERResponse:
    """Single-text NER — routed through the micro-batch queue."""
    raw = await _submit(req.text, req.entity_classes, req.threshold)
    return NERResponse(entities=_to_spans(raw))


@app.post("/ner/batch", response_model=BatchNERResponse)
async def ner_batch(req: BatchNERRequest) -> BatchNERResponse:
    """Batch NER — each text is submitted to the same micro-batch queue so it
    co-batches with concurrent single-text traffic. Preserves per-text ordering."""
    if not req.texts:
        return BatchNERResponse(results=[])
    raws = await asyncio.gather(*(_submit(text, req.entity_classes, req.threshold) for text in req.texts))
    return BatchNERResponse(results=[_to_spans(r) for r in raws])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)  # noqa: S104
