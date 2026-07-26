"""Content-addressed cache-key builder shared by the entailment verifier blocks.

Key = ``nlp:v1:entailment_cache:<kind>:<sha256hex>`` where the digest covers
every field that can change the verifier's verdict for otherwise-identical
text: the model actually serving the call, the prompt TEMPLATE version (the
existing ``template_id`` strings — e.g. ``claim_entailment_v1`` — already carry
a version suffix bumped whenever the prompt/meaning-tables change; see
``claim_entailment.py``/``relation_entailment.py`` module docstrings), and the
verifier's own input fields (entity/predicate refs, claim_type/polarity or
subject/object, and the verbatim evidence quote).

IMPORTANT: bump the caller's ``template_id`` (e.g. ``claim_entailment_v1`` ->
``claim_entailment_v2``) on ANY change to the system prompt, the claim-type /
predicate MEANING tables, or the output schema. Because ``template_id`` is
part of the key, a bump auto-evicts every verdict cached under the old
semantics — mirrors ``rag_chat.completion_cache``'s ``RESOLVER_VERSION``
convention for the exact same reason (a stale verdict computed under an old
prompt is semantically wrong even though the raw text input is unchanged).

Two distinct (claim, evidence) pairs must never collide, and the SAME pair
(same model, template, and fields) must always resolve to the SAME key
regardless of dict key ordering or incidental whitespace differences the
callers already ``.strip()`` before this function sees them.
"""

from __future__ import annotations

import hashlib

_NAMESPACE = "nlp:v1:entailment_cache"


def build_cache_key(kind: str, model_id: str, template_id: str, *fields: str) -> str:
    """Return a content-addressed Valkey key for one verifier call.

    Args:
        kind: cache sub-namespace, e.g. ``"claim"`` or ``"relation"`` — keeps the
            two verifiers' keyspaces disjoint even if a field collision were
            otherwise possible.
        model_id: the model actually serving the call (provenance/version tag).
        template_id: the prompt's own version string (see module docstring).
        *fields: the verifier's input fields in a FIXED, caller-defined order
            (e.g. entity_ref, claim_type, polarity, evidence for claims;
            subject_ref, predicate, object_ref, evidence for relations).

    Returns:
        ``"nlp:v1:entailment_cache:<kind>:<sha256-hex>"``.
    """
    # A literal "\x1f" (unit separator) joins segments so that no combination of
    # field VALUES containing the join character can produce a collision between
    # two otherwise-distinct inputs (plain ":" or "|" can appear in evidence text).
    raw = "\x1f".join((kind, model_id, template_id, *fields))
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"{_NAMESPACE}:{kind}:{digest}"
