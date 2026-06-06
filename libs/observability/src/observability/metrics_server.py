"""Standalone metrics + healthz HTTP server for worker processes.

Background
----------
Worker entrypoints (no FastAPI app) historically had no way to expose
``/metrics`` to Prometheus.  Some workers shipped an ad-hoc
``prometheus_client.start_http_server(port)`` call, which spawns a daemon
thread and prevents both graceful shutdown and a ``/healthz`` probe.

This module provides ``start_metrics_server`` — a tiny ASGI app
(Starlette + uvicorn) that runs inside the worker's own asyncio event loop
and exposes:

  * ``GET /metrics``  — Prometheus exposition (from the supplied
    ``CollectorRegistry`` or the global default).
  * ``GET /healthz``  — JSON liveness probe; optionally backed by a
    user-supplied callable.

The handle returned by ``start_metrics_server`` exposes ``aclose()`` so
the worker's existing SIGTERM handler can shut the server down cleanly.

Public API is frozen — downstream phases of the worker-metrics rollout
depend on it.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket as _socket
from typing import TYPE_CHECKING

import structlog
import uvicorn
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

if TYPE_CHECKING:
    from collections.abc import Callable

    from prometheus_client.registry import CollectorRegistry
    from starlette.requests import Request

logger = structlog.get_logger(__name__)

__all__ = ["MetricsServerHandle", "start_metrics_server"]


class MetricsServerHandle:
    """Handle returned by :func:`start_metrics_server`.

    Owns the underlying ``uvicorn.Server`` instance plus the asyncio
    ``Task`` running ``server.serve()``.  Call :meth:`aclose` from your
    worker shutdown path to stop the server.
    """

    def __init__(
        self,
        *,
        server: uvicorn.Server,
        task: asyncio.Task[None],
        service_name: str,
        port: int,
    ) -> None:
        # We keep the requested port on the handle so callers/tests can
        # discover the bound socket even when ``port=0`` was requested
        # for an ephemeral bind.  The bound port is read from the
        # underlying server's first socket once it has started serving.
        self._server = server
        self._task = task
        self._service_name = service_name
        self._requested_port = port
        self._closed = False

    @property
    def bound_port(self) -> int:
        """Return the actual port the server is listening on.

        Returns the requested port if the server has not yet finished
        binding (rare — callers normally await ``started=True`` before
        reading this).
        """
        # uvicorn sets server.servers after startup; each has a list of
        # asyncio sockets.  We grab the first bound socket's port number
        # because that is the only one we ever bind.
        for server in getattr(self._server, "servers", []):
            for sock in getattr(server, "sockets", []):
                try:
                    return int(sock.getsockname()[1])
                except OSError:
                    continue
        return self._requested_port

    async def aclose(self, timeout_s: float = 5.0) -> None:
        """Stop the metrics server.

        Safe to call multiple times; subsequent calls are no-ops.  If the
        server does not exit within ``timeout_s`` the task is cancelled.
        """
        if self._closed:
            return
        self._closed = True
        # uvicorn's documented shutdown signal — flips its internal loop
        # condition so the next iteration exits cleanly.
        self._server.should_exit = True
        try:
            await asyncio.wait_for(self._task, timeout=timeout_s)
        except TimeoutError:
            # Hard cancel as a last resort; do NOT raise — shutdown must
            # be best-effort so the worker can finish exiting.
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        except asyncio.CancelledError:
            pass
        logger.info(
            "metrics_server_stopped",
            service_name=self._service_name,
            port=self._requested_port,
        )


def _build_app(
    *,
    service_name: str,
    registry: CollectorRegistry,
    include_healthz: bool,
    liveness_probe: Callable[[], bool] | None,
) -> Starlette:
    """Build the Starlette app that exposes /metrics (+ optional /healthz)."""

    async def metrics_endpoint(_request: Request) -> Response:
        # Use the explicit ``registry`` so callers can isolate their
        # metrics in tests; falls back to the global REGISTRY by default
        # so existing prometheus_client.Counter(...) calls just work.
        payload = generate_latest(registry)
        return Response(content=payload, media_type=CONTENT_TYPE_LATEST)

    async def healthz_endpoint(_request: Request) -> JSONResponse:
        # When no probe is supplied we always return healthy — equivalent
        # to a TCP-style "process is up" check.
        is_healthy = True if liveness_probe is None else bool(liveness_probe())
        status_code = 200 if is_healthy else 503
        body = {
            "status": "ok" if is_healthy else "unhealthy",
            "service": service_name,
        }
        return JSONResponse(body, status_code=status_code)

    routes: list[Route] = [Route("/metrics", metrics_endpoint, methods=["GET"])]
    if include_healthz:
        routes.append(Route("/healthz", healthz_endpoint, methods=["GET"]))
    return Starlette(routes=routes)


def start_metrics_server(
    *,
    service_name: str,
    port: int = 9100,
    addr: str = "0.0.0.0",  # noqa: S104 — workers run inside container networks
    registry: CollectorRegistry | None = None,
    include_healthz: bool = True,
    liveness_probe: Callable[[], bool] | None = None,
) -> MetricsServerHandle:
    """Start a ``/metrics`` (+ ``/healthz``) HTTP server in the current loop.

    Parameters
    ----------
    service_name:
        Used in log events and in the ``/healthz`` JSON body.
    port:
        TCP port to bind.  ``0`` means "ephemeral" (the OS picks a free
        port); the bound port is then available via
        :attr:`MetricsServerHandle.bound_port` for tests.
    addr:
        Bind address — defaults to ``0.0.0.0`` because workers normally
        run inside a container network where Prometheus reaches them by
        DNS.
    registry:
        Prometheus registry to expose; defaults to the global
        ``prometheus_client.REGISTRY`` so module-level
        ``Counter(...)`` calls Just Work.
    include_healthz:
        If True (the default), the server also exposes ``GET /healthz``.
    liveness_probe:
        Optional callable returning ``True`` while the worker is healthy.
        When it returns ``False``, ``/healthz`` responds with HTTP 503 so
        Kubernetes/Compose health checks can restart the container.

    Returns
    -------
    MetricsServerHandle
        Cancel via :meth:`MetricsServerHandle.aclose`.

    Raises
    ------
    OSError
        If the requested port is already in use.  The caller (typically
        the worker's entrypoint) decides whether to abort or continue.
    """
    selected_registry = registry if registry is not None else REGISTRY

    app = _build_app(
        service_name=service_name,
        registry=selected_registry,
        include_healthz=include_healthz,
        liveness_probe=liveness_probe,
    )

    # log_level="warning" keeps uvicorn from spamming every request — the
    # worker already emits the events that actually matter via structlog.
    config = uvicorn.Config(
        app,
        host=addr,
        port=port,
        log_level="warning",
        access_log=False,
        lifespan="off",  # no lifespan events — keeps shutdown crisp
    )
    server = uvicorn.Server(config)

    # Pre-bind the listening socket ourselves so a port collision
    # raises OSError from this function.  We deliberately do NOT call
    # ``uvicorn.Config.bind_socket()`` because it calls ``sys.exit(1)``
    # on failure (see uvicorn/config.py), which would kill the worker
    # process instead of letting the caller handle the error.
    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    try:
        sock.bind((addr, port))
    except OSError as exc:
        sock.close()
        logger.error(
            "metrics_server_bind_failed",
            service_name=service_name,
            port=port,
            addr=addr,
            error=str(exc),
        )
        # Re-raise — callers can `except OSError` to log/continue.
        raise
    sock.listen(128)
    sock.setblocking(False)

    # Hand uvicorn the already-bound socket; this also unblocks the
    # ``ephemeral port=0`` path because we now know the real port.
    async def _serve() -> None:
        # uvicorn.Server.serve(sockets=[sock]) skips its own bind step
        # and uses the socket we created above.
        await server.serve(sockets=[sock])

    loop = asyncio.get_event_loop()
    task = loop.create_task(_serve(), name=f"metrics-server[{service_name}]")

    handle = MetricsServerHandle(
        server=server,
        task=task,
        service_name=service_name,
        # If port=0 was requested, prefer the real bound port for clarity
        # in logs and from MetricsServerHandle.bound_port.
        port=int(sock.getsockname()[1]) if port == 0 else port,
    )
    logger.info(
        "metrics_server_started",
        service_name=service_name,
        port=handle._requested_port,
        addr=addr,
    )
    return handle
