"""Content-addressed deep-extraction result cache (2026-07-26 cost audit).

WHY THIS EXISTS
----------------
The only dedup Block 10 (deep LLM extraction) had before this was the base
Kafka consumer's 24h event_id replay guard. That guard is scoped to a single
``(group_id, event_id)`` pair and misses every one of these real cases:

  - Wire-syndicated duplicate articles: the SAME story published under
    different ``doc_id``/``event_id`` by multiple sources — the article text
    (and therefore the extraction window text) is identical, but the guard
    never sees it because the event_id differs.
  - Post-TTL redeliveries: any redelivery more than 24h after the original
    processing attempt falls outside the guard's window entirely.
  - DLQ/backfill re-runs: replaying a dead-lettered or backfilled article
    re-invokes the SAME extraction call the platform already paid for.
  - Consumer-restart-driven reprocessing: an in-flight article whose consumer
    pod restarts mid-handler is redelivered and starts a fresh extraction call.

Every one of these re-pays the FULL deep-extraction LLM cost (the most
expensive call in the pipeline) for content that has already been extracted.

An existing hook — ``LLMScoreRepository.exists()`` — was investigated as a
candidate for reuse and rejected; see the module-level note in
``deep_extraction.py`` (search "llm_score investigation") for the full
rationale. In short: it is a Postgres-backed, doc_id-scoped ledger built for
the (unrelated) relevance-scoring worker — it cannot catch cross-doc_id
content duplication (the dominant case here) and it stores a float score, not
an extraction payload. This module is a purpose-built replacement.

DESIGN
------
Storage: Valkey (this repo's standard fast/TTL-native cache layer — see
ADR-0004), reusing the SAME ``ValkeyClient`` instance the article consumer
already holds for its retry-attempt counter (``self._dedup_client``). No new
infrastructure connection is introduced.

Key: ``nlp:v1:extraction_cache:<sha256 hex>`` where the hash covers
``model_id`` + the FULLY RENDERED prompt (which already embeds the
DEEP_EXTRACTION template's ``content_hash`` — see ``PromptTemplate`` in
libs/prompts — plus the type-tagged entity list plus the window text). Hashing
the rendered prompt rather than a bare ``version`` string is the critical
correctness property here: a prompt template EDIT changes ``content_hash``
(and therefore the rendered prompt) even when nobody remembers to bump
``version``, so a stale cached extraction can never be served after a prompt
change goes out. See PromptTemplate.__post_init__ for how content_hash is
computed as a 12-char sha256 prefix of the raw template body.

TTL: 30 days (``deep_extraction_cache_ttl_seconds``, see ``Settings``). Long
enough to cover backfill/DLQ replay lag measured in weeks; bounded so entries
cannot live forever if a downstream invalidation path is ever missed.

Failure mode: EVERY operation is fail-open. A Valkey outage must degrade to
"the extraction cache did not exist" (i.e. behave exactly like the pre-cache
code path), never break or block extraction.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

import structlog  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]

#: Valkey key prefix per ADR-0004 taxonomy: <scope>:<version>:<resource>:<id>.
_KEY_PREFIX = "nlp:v1:extraction_cache"

#: Default TTL — overridden by ``Settings.deep_extraction_cache_ttl_seconds``
#: at call sites; kept here as a safe fallback for direct instantiation (tests).
DEFAULT_TTL_SECONDS = 2_592_000  # 30 days


def build_cache_key(*, model_id: str, prompt: str) -> str:
    """Build the content-addressed Valkey key for one extraction call.

    ``prompt`` is the FULLY RENDERED prompt string (template body + type-tagged
    entity list + window text already substituted in by ``_build_prompt``). Its
    content therefore already encodes the prompt template's content, so hashing
    it (together with ``model_id``) is sufficient to invalidate on ANY of:
    a template edit, an entity-list change, or a window-text change — without
    needing to separately track a prompt version number that could be bumped
    (or not bumped) independently of the content.
    """
    digest = hashlib.sha256(f"{model_id}\n{prompt}".encode()).hexdigest()
    return f"{_KEY_PREFIX}:{digest}"


class DeepExtractionCache:
    """Valkey-backed content-addressed cache for Block 10 extraction results.

    All operations are best-effort: a Valkey error is logged and treated as a
    cache miss (``get``) or silently dropped (``set``) — this cache is a cost
    optimisation, never a correctness dependency, so it must never be able to
    fail an extraction that would otherwise have succeeded.
    """

    def __init__(self, client: ValkeyClient, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._client = client
        self._ttl_seconds = ttl_seconds

    async def get(self, *, model_id: str, prompt: str) -> dict[str, Any] | None:
        """Return the cached extraction result dict, or ``None`` on a miss.

        Also returns ``None`` (never raises) on Valkey unavailability or a
        corrupt cached payload — the caller falls through to a real LLM call.
        """
        key = build_cache_key(model_id=model_id, prompt=prompt)
        try:
            raw = await self._client.get(key)
        except Exception as exc:  # Valkey down/unreachable — fail open to a miss.
            logger.warning("deep_extraction_cache.get_failed", key=key, error=str(exc))
            return None
        if raw is None:
            return None
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            # Corrupt entry — treat as a miss rather than propagate a parse
            # error into the extraction path. A subsequent `set()` overwrites it.
            logger.warning("deep_extraction_cache.corrupt_entry", key=key)
            return None
        if not isinstance(parsed, dict):
            return None
        return parsed

    async def set(self, *, model_id: str, prompt: str, result: dict[str, Any]) -> None:
        """Write *result* to the cache under the content-addressed key.

        Best-effort: a Valkey write failure is logged and swallowed — losing a
        cache write only forgoes a future cost saving, it never corrupts data.
        """
        key = build_cache_key(model_id=model_id, prompt=prompt)
        try:
            await self._client.set(key, json.dumps(result), ttl=self._ttl_seconds)
        except Exception as exc:
            logger.warning("deep_extraction_cache.set_failed", key=key, error=str(exc))
