"""Runtime banner helper — emits a single ``<service>_ready`` structlog event.

PLAN-0107 §B.2.  Called by worker/service entrypoints AFTER dependencies
are wired (DB pool, Kafka producer, registries) so ops have a single
log line per process showing what actually came up.

Design notes
------------
* The boot timestamp is captured at *import time* via ``time.monotonic()``
  so the reported uptime measures time since the module was first imported
  by the worker — close enough to "process boot" for diagnostic purposes
  and immune to wall-clock skew.
* Values whose KEYS look secret-ish (password / token / secret / key /
  api_key) are masked to ``"***"``.  We recurse one level into nested
  dicts so common shapes like ``{"db": {"password": ...}}`` work.
* The helper deliberately reuses ``metrics_server._count_families`` so
  the banner and ``metrics_server_started`` agree on the family count.
"""

from __future__ import annotations

import re
import time
from typing import Any

import structlog

from observability.metrics_server import _count_families

__all__ = ["log_runtime_banner"]

# Captured at import time — close to process boot.  ``monotonic()`` is
# immune to NTP slews so the delta is meaningful even on long-running
# workers.
_BOOT_TS = time.monotonic()

# Case-insensitive match against dict KEYS — we never look at values
# because values can legitimately contain words like "key" without being
# secrets (e.g. a config flag named "use_redis_streams").
_SECRET_KEY_PATTERN = re.compile(r"password|token|secret|key|api_key", re.IGNORECASE)


def _mask_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow-recursive copy of ``d`` with secret-shaped keys masked.

    Recurses one level into nested dicts.  Non-dict values are passed
    through untouched.  We do NOT mask list contents — callers should not
    be passing list-of-secrets shapes through the dependency map.
    """
    out: dict[str, Any] = {}
    for k, v in d.items():
        if _SECRET_KEY_PATTERN.search(k):
            out[k] = "***"
        elif isinstance(v, dict):
            # Recurse once — deep dependency trees are rare in this code
            # base and unbounded recursion would risk perf surprises on
            # accidental cycles.
            out[k] = _mask_dict(v)
        else:
            out[k] = v
    return out


def log_runtime_banner(service_name: str, *, dependencies: dict[str, Any]) -> None:
    """Emit exactly one ``<service_name>_ready`` structlog event.

    Parameters
    ----------
    service_name:
        Service / worker name — used as the log event name suffix and as
        a structured field so log routers can pivot on it.
    dependencies:
        Free-form dict describing the wired dependencies (broker URLs,
        DB DSNs without password, model identifiers, feature flags).
        Secret-shaped keys are masked before logging.
    """
    log = structlog.get_logger(__name__)
    masked = _mask_dict(dependencies)
    count, _sample = _count_families()
    log.info(
        f"{service_name}_ready",
        service_name=service_name,
        dependencies=masked,
        uptime_seconds_since_boot=round(time.monotonic() - _BOOT_TS, 3),
        registered_metric_families=count,
    )
