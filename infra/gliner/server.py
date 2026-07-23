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
import ctypes
import ctypes.util
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
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

# ── Bounded-memory knobs (gliner OOM fix, 2026-07-16) ──────────────────────────
# Root cause of the recurring OOMKill (anon-rss ramps to the cap over hours even
# with GLINER_MAX_BATCH already halved to 8) is NOT a single activation spike but
# slow glibc-allocator RETENTION under a variable-length CPU-tensor workload:
# every forward pass allocates transient tensors whose size depends on the padded
# sequence length of the batch; glibc keeps freed blocks in per-arena free lists
# and, with variable-length allocations, the RSS high-water mark ratchets upward
# (fragmentation) and is never returned to the OS. Three complementary bounds:
#
#   1. GLINER_MAX_INPUT_CHARS — hard server-side cap on per-text length before
#      inference. Defence-in-depth: bounds the PEAK padded activation regardless
#      of what any caller sends (the news backfill floods long documents). The
#      nlp-pipeline already truncates to ~450 *words*, but that is a loose proxy
#      for subword tokens and is caller-side only; this enforces a firm ceiling.
#   2. A dedicated SINGLE-thread inference executor (see _INFERENCE_EXECUTOR):
#      pins every forward pass to ONE OS thread so tensor allocations come from a
#      single glibc arena instead of one-per-executor-thread — the dominant
#      fragmentation source. Inference is already serialised by the collector, so
#      one worker costs no throughput.
#   3. malloc_trim(0) after each flush (see _malloc_trim) — actively returns the
#      freed arena pages to the OS, flattening the ramp instead of letting the
#      working set ratchet to the cap.
#
# GLINER_MAX_INFERENCES is an optional backstop: recycle the process after N
# forward passes so k8s restarts it with a fresh heap. Disabled by default (0);
# the three bounds above should hold the working set flat on their own.
GLINER_MAX_INPUT_CHARS = int(os.environ.get("GLINER_MAX_INPUT_CHARS", "4000"))
GLINER_MAX_INFERENCES = int(os.environ.get("GLINER_MAX_INFERENCES", "0"))

# Adaptive per-forward-pass activation budget (gliner OOM residual, 2026-07-22).
# The count cap (GLINER_MAX_BATCH) alone does NOT bound peak activation memory:
# batch_predict_entities pads every text in a group to the LONGEST text, and
# GLiNER's span-enumeration tensors scale as batch_size × padded_seq_len ×
# max_span_width. So a batch of 8 SHORT sections and a batch of 8 max-length
# (GLINER_MAX_INPUT_CHARS) sections have very different peaks for the SAME count.
# Live evidence: the arena-fragmentation ramp is fixed (working set flat ~2.4Gi),
# but a FULL batch-8 forward pass peaks at ~6.15Gi anon-rss and occasionally
# clears the 8Gi cap under a backfill burst of longer sections (~1 OOMKill/day).
#
# GLINER_MAX_BATCH_CHARS bounds peak DETERMINISTICALLY by capping the padded-
# activation proxy (batch_size × longest-text-chars) per forward pass, so a batch
# adaptively SHRINKS when its texts are long and stays full (up to GLINER_MAX_BATCH)
# when they are short — bounding memory without sacrificing normal-section
# throughput. 0 disables it (pure count batching, prior behaviour). The group
# always keeps at least its seed item (already truncated to GLINER_MAX_INPUT_CHARS),
# so a single oversized text still runs.
GLINER_MAX_BATCH_CHARS = int(os.environ.get("GLINER_MAX_BATCH_CHARS", "0"))

# Single-thread pool: all model forward passes run here so their (variable-length)
# CPU tensors are allocated from ONE glibc malloc arena. run_in_executor(None,...)
# used the default pool, which can grow to multiple threads over the process
# lifetime → multiple arenas → compounding fragmentation. thread_name_prefix keeps
# the OOM-killer's task name (pt_main_thread) legible in dmesg.
_INFERENCE_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gliner-infer")

# libc handle for malloc_trim(0). Best-effort: None on non-glibc (musl/alpine) or
# if resolution fails — the trim then simply no-ops.
try:
    _LIBC: ctypes.CDLL | None = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
except OSError:  # pragma: no cover — platform without a resolvable libc
    _LIBC = None


def _malloc_trim() -> None:
    """Return free heap pages to the OS (glibc ``malloc_trim(0)``).

    Best-effort: no-ops when libc/malloc_trim is unavailable (musl, macOS). Cheap
    relative to a GLiNER forward pass, so it is safe to call after every flush."""
    if _LIBC is None:
        return
    try:
        _LIBC.malloc_trim(0)
    except (AttributeError, OSError):  # pragma: no cover — malloc_trim missing (musl)
        pass


def _would_exceed_batch_chars(group_size: int, current_max_len: int, next_len: int) -> bool:
    """True if adding a text of ``next_len`` chars would push the group's padded-
    activation proxy over ``GLINER_MAX_BATCH_CHARS``.

    The proxy is ``batch_size × longest-text-length`` because a batched forward
    pass pads every text to the longest one — a single long text inflates the peak
    for the WHOLE batch, so summing lengths would under-count it (a batch of one
    4000-char text + seven 10-char texts pads all eight to 4000). Modelling the
    max-length driver is what actually bounds peak memory.

    Disabled (always False) when GLINER_MAX_BATCH_CHARS <= 0."""
    if GLINER_MAX_BATCH_CHARS <= 0:
        return False
    new_max = max(current_max_len, next_len)
    return (group_size + 1) * new_max > GLINER_MAX_BATCH_CHARS


def _truncate_input(text: str) -> str:
    """Hard char-cap on a single inference input (bounds peak activation)."""
    if GLINER_MAX_INPUT_CHARS > 0 and len(text) > GLINER_MAX_INPUT_CHARS:
        return text[:GLINER_MAX_INPUT_CHARS]
    return text


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

    __slots__ = ("future", "labels", "text", "threshold")

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
    """One padded forward pass over N texts sharing (labels, threshold).

    Wrapped in ``torch.inference_mode`` (a no-op if torch is unavailable) so no
    autograd graph / grad buffers are ever allocated or retained for inference —
    a further guard against per-request tensor accumulation. Freed pages are
    returned to the OS via malloc_trim after the pass completes."""
    try:
        import torch  # type: ignore[import-not-found]

        with torch.inference_mode():
            out = model.batch_predict_entities(texts, labels, threshold=threshold)
    except ImportError:  # pragma: no cover — torch always present in the image
        out = model.batch_predict_entities(texts, labels, threshold=threshold)
    finally:
        # Runs on the single inference thread, right after the transient tensors
        # for this pass go out of scope — the ideal point to hand pages back.
        _malloc_trim()
    return out  # type: ignore[no-any-return]


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
        # Pinned single-thread executor (one glibc arena) instead of the default
        # pool — see _INFERENCE_EXECUTOR. Inference is already serialised here.
        results = await loop.run_in_executor(_INFERENCE_EXECUTOR, _predict_batch, model, texts, labels, threshold)
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
    _maybe_recycle()


def _maybe_recycle() -> None:
    """Optional backstop: exit the process after GLINER_MAX_INFERENCES forward
    passes so the orchestrator restarts it with a fresh heap.

    Disabled by default (GLINER_MAX_INFERENCES=0). This is a *bound*, not the
    primary fix (arena-pinning + malloc_trim + input cap keep the working set
    flat); enable it only if a residual slow creep is observed in prod. The exit
    is graceful from the pod's view — replicas>1 or a rollout keep NER available;
    with replicas=1 the readiness probe drains it and k8s restarts within seconds.
    """
    if GLINER_MAX_INFERENCES <= 0:
        return
    if _METRICS["flushed_total"] % GLINER_MAX_INFERENCES == 0:
        _log("gliner_worker_recycle", flushed_total=_METRICS["flushed_total"], reason="max_inferences")
        # os._exit avoids running atexit/finalizers mid-inference; kubelet restarts.
        os._exit(0)


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
            # Track the longest text in the group: peak padded activation scales
            # with len(group) × group_max_len, so the char-budget guard needs both.
            group_max_len = len(first.text)
            deadline = time.monotonic() + GLINER_BATCH_WAIT_MS / 1000.0

            # Re-scan deferred buffer for same-key items first (no waiting). Skip
            # any that would breach the padded-activation budget — they stay
            # deferred and seed/join a later (smaller) batch.
            still_deferred: list[_QueueItem] = []
            for it in deferred:
                if (
                    len(group) < GLINER_MAX_BATCH
                    and _group_key(it.labels, it.threshold) == key
                    and not _would_exceed_batch_chars(len(group), group_max_len, len(it.text))
                ):
                    group.append(it)
                    group_max_len = max(group_max_len, len(it.text))
                else:
                    still_deferred.append(it)
            deferred = still_deferred

            # Drain fresh arrivals until full (by count OR char budget) or the wait
            # window expires.
            while len(group) < GLINER_MAX_BATCH:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    nxt = await asyncio.wait_for(_queue.get(), timeout=remaining)
                except TimeoutError:
                    break
                if _group_key(nxt.labels, nxt.threshold) != key:
                    # Different key — defer for a subsequent loop (its own batch).
                    deferred.append(nxt)
                elif _would_exceed_batch_chars(len(group), group_max_len, len(nxt.text)):
                    # Same key but adding it would breach the activation budget —
                    # defer it and close this batch to bound peak memory.
                    deferred.append(nxt)
                    break
                else:
                    group.append(nxt)
                    group_max_len = max(group_max_len, len(nxt.text))

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
    # Enforce the hard input cap here so EVERY path (/ner and /ner/batch) is
    # bounded before the text ever reaches a padded forward pass.
    await _queue.put(_QueueItem(_truncate_input(text), labels, threshold, future))
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
    _log(
        "gliner_started",
        max_batch=GLINER_MAX_BATCH,
        batch_wait_ms=GLINER_BATCH_WAIT_MS,
        max_input_chars=GLINER_MAX_INPUT_CHARS,
        max_inferences=GLINER_MAX_INFERENCES,
        malloc_trim=_LIBC is not None,
    )
    try:
        yield
    finally:
        if _collector_task is not None:
            _collector_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await _collector_task
        _INFERENCE_EXECUTOR.shutdown(wait=False, cancel_futures=True)


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
