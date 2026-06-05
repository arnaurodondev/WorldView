"""CITATION_JUDGE — 0-3 faithfulness scorer for claim/snippet pairs.

Source of truth for the prompt body previously inlined as ``_CITATION_RUBRIC``
in ``services/rag-chat/src/rag_chat/application/use_cases/score_citation_accuracy.py``.

The rubric is fenced with explicit ``<<<CLAIM …>>>`` / ``<<<SNIPPET …>>>``
delimiters so adversarial chunk text cannot override the judge instruction
(F-S01). The same delimiters appear in ``_INJECTION_TOKENS`` in the use case
so any attempt to embed the framing inside the inputs is redacted *before*
``render()`` is called (belt-and-braces).
"""

from __future__ import annotations

from prompts._base import PromptTemplate

# Verbatim copy of the previous _CITATION_RUBRIC. DO NOT edit body — the
# semantics of the 0-3 scale are part of the v1.0 contract and bumping
# requires a new version + recalibration of downstream gauges.
_TEMPLATE = """\
You are evaluating whether a snippet supports a chat assistant's claim.
The claim may be a direct quote OR a synthesis/paraphrase of multiple sources.

<<<CLAIM START>>>
{claim}
<<<CLAIM END>>>

<<<SNIPPET START>>>
{snippet}
<<<SNIPPET END>>>

Score the snippet's support of the claim on this 0-3 scale:
- 0: Snippet is irrelevant to the claim
- 1: Snippet is tangentially related but does not support the specific claim
- 2: Snippet supports the claim — EITHER directly OR by supporting a paraphrase
     or synthesis of which this claim is a faithful summary.
- 3: Snippet directly answers/contains the claim verbatim or near-verbatim.

Respond with ONLY a single digit 0, 1, 2, or 3."""


CITATION_JUDGE = PromptTemplate(
    name="citation_judge",
    version="1.0",
    description="0-3 faithfulness scorer for [cN] claim-snippet pairs.",
    template=_TEMPLATE,
    parameters=frozenset({"claim", "snippet"}),
)
