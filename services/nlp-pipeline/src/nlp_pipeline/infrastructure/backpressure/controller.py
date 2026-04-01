"""Backpressure controller — asyncio-based Ollama queue depth management.

Uses asyncio.Semaphore to bound concurrent Ollama requests (Block 7 + Block 10).
When the semaphore is exhausted, Kafka partitions are paused until the depth
drops below RESUME_OLLAMA_QUEUE_DEPTH.

NEVER uses threading.sleep — asyncio only (PRD §6.7 T-C-3-05).
"""

from __future__ import annotations

import asyncio

import structlog  # type: ignore[import-untyped]

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class BackpressureController:
    """Controls Ollama request concurrency via an asyncio.Semaphore.

    Callers acquire the semaphore before dispatching to Ollama and release
    it after the response (or error). When the semaphore is exhausted (depth
    reaches max_depth), callers block until a slot frees.

    The ``is_paused`` property signals to the Kafka consumer loop that it
    should pause partition polling.
    """

    def __init__(self, max_depth: int, resume_depth: int) -> None:
        if resume_depth >= max_depth:
            msg = f"resume_depth ({resume_depth}) must be < max_depth ({max_depth})"
            raise ValueError(msg)
        self._max_depth = max_depth
        self._resume_depth = resume_depth
        self._semaphore = asyncio.Semaphore(max_depth)
        self._current_depth: int = 0
        self._paused: bool = False

    # ── Depth tracking ────────────────────────────────────────────────────────

    @property
    def current_depth(self) -> int:
        """Current number of in-flight Ollama requests."""
        return self._current_depth

    @property
    def is_paused(self) -> bool:
        """True when Kafka consumer partitions should be paused."""
        return self._paused

    def _update_pause_state(self) -> None:
        """Update pause state based on current depth thresholds."""
        if not self._paused and self._current_depth >= self._max_depth:
            self._paused = True
            logger.info(
                "backpressure.paused",
                depth=self._current_depth,
                max_depth=self._max_depth,
            )
        elif self._paused and self._current_depth <= self._resume_depth:
            self._paused = False
            logger.info(
                "backpressure.resumed",
                depth=self._current_depth,
                resume_depth=self._resume_depth,
            )

    # ── Semaphore context manager ─────────────────────────────────────────────

    async def acquire(self) -> None:
        """Acquire a slot in the Ollama queue.

        Blocks (asyncio-await) until a slot is available.
        """
        await self._semaphore.acquire()
        self._current_depth += 1
        self._update_pause_state()

    def release(self) -> None:
        """Release a slot, decrement current depth."""
        self._semaphore.release()
        self._current_depth = max(0, self._current_depth - 1)
        self._update_pause_state()

    async def __aenter__(self) -> BackpressureController:
        await self.acquire()
        return self

    async def __aexit__(self, *_: object) -> None:
        self.release()

    # ── Prometheus gauge support ──────────────────────────────────────────────

    def gauge_value(self) -> int:
        """Return current depth for Prometheus Gauge (s6_ollama_queue_depth_current)."""
        return self._current_depth

    # ── Kafka integration helpers ─────────────────────────────────────────────

    async def wait_for_resume(self, poll_interval: float = 0.1) -> None:
        """Async wait until the controller is no longer paused.

        Called by the Kafka consumer loop before polling the next message.
        Uses asyncio.sleep — NEVER threading.sleep.
        """
        while self._paused:
            await asyncio.sleep(poll_interval)
