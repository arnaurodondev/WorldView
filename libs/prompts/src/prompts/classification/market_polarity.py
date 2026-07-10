"""Prediction-market polarity classification prompt (S7 KG — PLAN-0056 Wave C3 / PRD-0033).

Mirrors the structure/versioning of
``libs/prompts/src/prompts/classification/article_relevance.py``: this module owns
ONLY the static system block (so it gets a content-hash + semver + shared
identifier); the caller (``MarketPolarityClassifier`` in the knowledge-graph
service) appends the dynamic "Question / Entity / Outcomes" trailer at call time —
that is why ``parameters`` is intentionally empty.

Semantics: polarity is the direction of a YES / affirmative resolution *for the
referenced entity*, NOT for the bettor:
  - "Will Company X miss Q3 earnings?"        → bearish for X (a miss hurts X).
  - "Will X's drug be approved by the FDA?"   → bullish for X (approval helps X).
  - question unrelated to the entity          → neutral.

Versioning:
- ``version="1.0"`` is the first release of this prompt. Bump the version (and the
  auto-computed content_hash follows) on ANY wording change, since a change alters
  classification semantics and breaks polarity comparability across the exposure
  ledger.
"""

from __future__ import annotations

from prompts._base import PromptTemplate

# DO NOT edit the template body without bumping ``version`` — the content_hash
# (auto-computed) is stored alongside each classified exposure for lineage.
MARKET_POLARITY_CLASSIFIER = PromptTemplate(
    name="market_polarity_classifier",
    version="1.0",
    description=(
        "Static system block instructing a small LLM to classify a prediction "
        "market's polarity (bullish|bearish|neutral) for a specific referenced "
        "entity, where polarity is the direction of a YES/affirmative resolution "
        "FOR THAT ENTITY. Used by MarketPolarityClassifier (knowledge-graph, "
        "DeepInfra OpenAI-compat small model). The dynamic Question/Entity/Outcomes "
        "trailer is appended at the call site — that's why ``parameters`` is empty."
    ),
    template=(
        "You are a financial prediction-market analyst. "
        "You are given a prediction-market question and ONE company or entity that "
        "the question references. Classify the market direction for THAT ENTITY, "
        "assuming the question resolves YES (the affirmative outcome happens).\n"
        '"bullish" = a YES/affirmative resolution is GOOD for the entity '
        "(its stock or standing would likely rise).\n"
        '"bearish" = a YES/affirmative resolution is BAD for the entity '
        "(its stock or standing would likely fall).\n"
        '"neutral" = the question is unrelated to the entity, or the direction '
        "for the entity is genuinely unclear.\n"
        "Examples:\n"
        'Question: "Will Company X miss Q3 earnings?" Entity: X -> bearish '
        "(a miss hurts X).\n"
        'Question: "Will X\'s drug be approved by the FDA?" Entity: X -> bullish '
        "(approval helps X).\n"
        'Question: "Will it rain in Seattle tomorrow?" Entity: X -> neutral '
        "(unrelated to X).\n"
        "If the question is ambiguous or unrelated to the entity, return neutral "
        "with a low confidence.\n"
        "Respond with ONLY valid JSON: "
        '{{"polarity": "bullish"|"bearish"|"neutral", '
        '"confidence": <float 0.0-1.0>, "reason": "<max 10 words in English>"}}'
    ),
    # No template parameters — the caller appends the dynamic
    # "\nQuestion: ...\nEntity: ...\nOutcomes: ..." trailer itself (keeps the
    # system/user split correct for the DeepInfra chat-completions path).
    parameters=frozenset(),
)
