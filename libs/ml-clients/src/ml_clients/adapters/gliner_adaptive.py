"""Adaptive GLiNER HTTP adapter — AIMD concurrency control.

Fans out one HTTP request per NER input and adjusts the number of concurrent
in-flight requests based on observed latency (Additive-Increase /
Multiplicative-Decrease). Automatically discovers the optimal concurrency for
the current deployment:

  - 1 CPU replica  → settles at 1 (CPU saturates per request)
  - N CPU replicas → settles at ~N (one active request per replica)
  - N GPU replicas → settles at N-2N (GPU allows more overlap per replica)

Usage::

    adapter = AdaptiveGLiNERHTTPAdapter(
        base_url="http://gliner-server:8080",
        initial_concurrency=2,
        max_concurrency=30,
        target_latency_ms=2000.0,
    )
    outputs = await adapter.batch_extract_entities(inputs)

See Also:
    ``gliner_http.py`` — fixed-concurrency HTTP adapter (simpler, no AIMD).
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import time
from typing import Any

import structlog

from ml_clients.dataclasses import EntityMention, NERInput, NEROutput
from ml_clients.errors import FatalError, RetryableError

logger = structlog.get_logger()


# ── ResizableSemaphore ────────────────────────────────────────────────────────


class ResizableSemaphore:
    """``asyncio.Semaphore`` with a runtime-adjustable permit limit.

    Unlike the stdlib semaphore (fixed at creation), ``set_limit(n)`` can
    grow or shrink the number of concurrent permits while the semaphore is
    in use.  When the limit increases, waiting coroutines are woken up
    immediately; when it decreases, the new lower bound is enforced on the
    next ``acquire`` (active holders are not interrupted).

    Args:
        initial: Starting number of concurrent permits (≥ 1).
        max_permits: Hard upper bound — ``set_limit`` will not exceed this.
    """

    def __init__(self, initial: int = 1, max_permits: int = 30) -> None:
        if initial < 1:
            raise ValueError(f"initial must be ≥ 1, got {initial}")
        if max_permits < initial:
            raise ValueError(f"max_permits ({max_permits}) must be ≥ initial ({initial})")
        self._limit: int = initial
        self._max: int = max_permits
        self._active: int = 0
        self._waiters: collections.deque[asyncio.Future[None]] = collections.deque()

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def current_limit(self) -> int:
        """Current concurrency limit (may differ from ``max_permits``)."""
        return self._limit

    @property
    def active(self) -> int:
        """Number of coroutines currently holding a permit."""
        return self._active

    # ── Limit adjustment ──────────────────────────────────────────────────────

    def set_limit(self, n: int) -> None:
        """Adjust the concurrency limit.

        Clamped to ``[1, max_permits]``.  If the limit increases, waiting
        coroutines are woken immediately (up to the added capacity).
        """
        new_limit = max(1, min(n, self._max))
        old_limit = self._limit
        self._limit = new_limit
        if new_limit > old_limit:
            # Wake waiters for the newly added capacity
            added = new_limit - old_limit
            to_wake = min(added, len(self._waiters))
            for _ in range(to_wake):
                if self._waiters:
                    fut = self._waiters.popleft()
                    if not fut.done():
                        fut.set_result(None)

    # ── Acquire / release ─────────────────────────────────────────────────────

    async def acquire(self) -> None:
        """Wait until a permit is available, then claim it."""
        while self._active >= self._limit:
            loop = asyncio.get_running_loop()
            fut: asyncio.Future[None] = loop.create_future()
            self._waiters.append(fut)
            try:
                await fut
            except asyncio.CancelledError:
                with contextlib.suppress(ValueError):
                    self._waiters.remove(fut)
                raise
        self._active += 1

    def release(self) -> None:
        """Release a permit.  Wakes one waiting coroutine if space allows."""
        if self._active <= 0:
            raise RuntimeError("ResizableSemaphore released more times than acquired")
        self._active -= 1
        if self._waiters and self._active < self._limit:
            fut = self._waiters.popleft()
            if not fut.done():
                fut.set_result(None)

    async def __aenter__(self) -> ResizableSemaphore:
        await self.acquire()
        return self

    async def __aexit__(self, *_args: Any) -> None:
        self.release()


# ── AIMDController ────────────────────────────────────────────────────────────


class AIMDController:
    """Additive-Increase / Multiplicative-Decrease concurrency controller.

    Adjusts a ``ResizableSemaphore`` limit based on observed request latency:

    * Fast response (rolling avg < target)    → limit += 1 (additive increase)
    * Slow response (rolling avg > 1.5x target) → limit -= 1 (additive decrease)
    * HTTP 5xx                                → limit -= 1
    * Timeout                                 → limit //= 2 (multiplicative decrease)

    Requires at least ``min_samples`` observations before making any adjustment
    to avoid over-reacting to the first few cold-start requests.

    Args:
        semaphore: The ``ResizableSemaphore`` to control.
        target_latency_ms: Desired request latency.  Concurrency is increased
            when the rolling average stays below this value.
        window_size: Number of recent samples used for the rolling average.
        min_samples: Minimum observations before AIMD adjustments begin.
    """

    def __init__(
        self,
        semaphore: ResizableSemaphore,
        target_latency_ms: float = 2000.0,
        window_size: int = 10,
        min_samples: int = 3,
    ) -> None:
        self._sem = semaphore
        self._target = target_latency_ms
        self._window: collections.deque[float] = collections.deque(maxlen=window_size)
        self._min_samples = min_samples

    @property
    def avg_latency_ms(self) -> float | None:
        """Rolling average latency (ms) across recent requests, or None if no data."""
        if not self._window:
            return None
        return sum(self._window) / len(self._window)

    def record_success(self, latency_ms: float) -> None:
        """Record a successful request and potentially adjust concurrency."""
        self._window.append(latency_ms)
        if len(self._window) < self._min_samples:
            return
        avg = sum(self._window) / len(self._window)
        current = self._sem.current_limit
        if avg < self._target:
            self._sem.set_limit(current + 1)
        elif avg > self._target * 1.5:
            self._sem.set_limit(current - 1)

    def record_failure(self, *, is_timeout: bool = False) -> None:
        """Record a failed request and reduce concurrency.

        Timeouts trigger a multiplicative decrease (÷2); other failures
        trigger an additive decrease (-1).
        """
        current = self._sem.current_limit
        if is_timeout:
            self._sem.set_limit(max(1, current // 2))
        else:
            self._sem.set_limit(max(1, current - 1))


# ── AdaptiveGLiNERHTTPAdapter ─────────────────────────────────────────────────


class AdaptiveGLiNERHTTPAdapter:
    """GLiNER HTTP adapter with AIMD adaptive concurrency.

    Implements the ``NERClient`` protocol.  ``batch_extract_entities`` fans out
    one HTTP request *per input text*, limited by an adaptive semaphore whose
    concurrency limit grows toward the server's throughput capacity and backs
    off under load or errors.

    With a single CPU GLiNER replica the limit will naturally settle at 1.
    With N replicas (``docker compose up --scale gliner-server=N``) it
    discovers N automatically — no configuration changes required.

    Args:
        base_url: Base URL of the GLiNER server (e.g. ``http://gliner-server:8080``).
        initial_concurrency: Starting semaphore limit (default: 2).
        max_concurrency: Hard upper bound on concurrent in-flight requests.
        target_latency_ms: AIMD target latency in milliseconds (default: 2 000 ms
            for CPU; use ~200 ms for GPU replicas).
        timeout_seconds: Per-request HTTP timeout.
        window_size: Rolling latency window size for AIMD averaging.
    """

    def __init__(
        self,
        base_url: str,
        initial_concurrency: int = 2,
        max_concurrency: int = 30,
        target_latency_ms: float = 2000.0,
        timeout_seconds: float = 60.0,
        window_size: int = 10,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._sem = ResizableSemaphore(initial=initial_concurrency, max_permits=max_concurrency)
        self._controller = AIMDController(
            semaphore=self._sem,
            target_latency_ms=target_latency_ms,
            window_size=window_size,
        )

    # ── Observability ─────────────────────────────────────────────────────────

    @property
    def current_concurrency(self) -> int:
        """Current adaptive concurrency limit."""
        return self._sem.current_limit

    @property
    def avg_latency_ms(self) -> float | None:
        """Rolling average request latency (ms), or None if no completed requests."""
        return self._controller.avg_latency_ms

    # ── NERClient protocol ────────────────────────────────────────────────────

    async def extract_entities(self, inp: NERInput) -> NEROutput:
        results = await self.batch_extract_entities([inp])
        return results[0]

    async def batch_extract_entities(self, inputs: list[NERInput]) -> list[NEROutput]:
        """Fan-out: one HTTP request per input, results in input order.

        All inputs are dispatched as independent concurrent tasks, limited by
        the adaptive semaphore.  ``asyncio.gather`` preserves order.
        """
        if not inputs:
            return []
        tasks = [self._extract_one(inp) for inp in inputs]
        return list(await asyncio.gather(*tasks))

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _extract_one(self, inp: NERInput) -> NEROutput:
        """Send a single-text request to the GLiNER server.

        Wrapped in the adaptive semaphore.  Records latency or failure to
        the AIMD controller after each call.
        """
        try:
            import httpx
        except ImportError as exc:
            raise FatalError("httpx not installed; add it to ml-clients dependencies") from exc

        async with self._sem:
            t0 = time.monotonic()
            try:
                payload: dict[str, Any] = {
                    "texts": [inp.text],
                    "entity_classes": inp.entity_classes,
                    "threshold": inp.threshold,
                }
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(f"{self._base_url}/ner/batch", json=payload)

                latency_ms = (time.monotonic() - t0) * 1000.0

                if resp.status_code == 503:
                    self._controller.record_failure(is_timeout=False)
                    raise RetryableError("GLiNER server unavailable (503)")
                if resp.status_code >= 500:
                    self._controller.record_failure(is_timeout=False)
                    raise RetryableError(f"GLiNER server 5xx: {resp.status_code}")
                if resp.status_code >= 400:
                    raise FatalError(f"GLiNER server 4xx: {resp.status_code} — {resp.text}")

                self._controller.record_success(latency_ms)
                data = resp.json()
                section_entities: list[dict[str, Any]] = data.get("results", [[]])[0]
                mentions = [
                    EntityMention(
                        text=str(e["text"]),
                        label=str(e["label"]),
                        start=int(e["start"]),
                        end=int(e["end"]),
                        score=float(e["score"]),
                    )
                    for e in section_entities
                ]
                logger.debug(
                    "gliner_adaptive_request_done",
                    latency_ms=round(latency_ms, 1),
                    concurrency_limit=self._sem.current_limit,
                    entities=len(mentions),
                )
                return NEROutput(mentions=mentions)

            except httpx.TimeoutException as exc:
                self._controller.record_failure(is_timeout=True)
                raise RetryableError(f"GLiNER server timeout: {exc}") from exc
            except httpx.ConnectError as exc:
                self._controller.record_failure(is_timeout=False)
                raise RetryableError(f"GLiNER server connection error: {exc}") from exc
            except (RetryableError, FatalError):
                raise
            except Exception as exc:
                raise FatalError(f"Unexpected GLiNER adaptive error: {exc}") from exc
