"""EntailmentCachePort — content-addressed result cache for entailment verifiers.

Why this exists
----------------
``claim_entailment.py`` and ``relation_entailment.py`` each ask a DeepInfra
verifier LLM a single binary question per (claim, evidence) / (relation,
evidence) pair. Both calls run at ``temperature=0.0`` (the DeepSeek/Qwen
extraction adapters hard-code this — see ``ml_clients.adapters.
deepseek_extraction``), so the SAME input always yields the SAME verdict: the
call is a pure, deterministic function of its prompt inputs. High per-article
fan-out plus duplicate/updated articles that quote the SAME evidence sentence
for the SAME entity/claim (wire-service syndication, corrected republishes,
recurring press-release boilerplate) mean the identical pair is very likely to
be re-verified — and re-paid-for — more than once.

This port lets both blocks skip the LLM call entirely on a cache hit. It is
intentionally tiny (get/set of a JSON-able verdict dict) so it can be backed by
Valkey (production) or an in-memory fake (tests) with no other dependencies.
"""

from __future__ import annotations

from typing import Any, Protocol


class EntailmentCachePort(Protocol):
    """Port for a content-addressed entailment-verdict cache.

    Implementations MUST be fail-open: a cache outage must never raise out of
    ``get``/``set`` and must never affect the verdict the caller ultimately
    uses (mirrors the fail-open design of the entailment blocks themselves).
    """

    async def get(self, key: str) -> dict[str, Any] | None:
        """Return the cached verdict dict for *key*, or ``None`` on a miss/error."""
        ...

    async def set(self, key: str, value: dict[str, Any], ttl: int) -> None:
        """Persist *value* under *key* for *ttl* seconds. Best-effort."""
        ...
