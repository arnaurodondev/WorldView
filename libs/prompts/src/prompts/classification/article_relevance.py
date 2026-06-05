"""Article relevance + sentiment scoring prompt (S6 NLP-pipeline — PRD-0026 §6.7 Flow B).

Migrated from ``services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/
article_relevance_scoring_worker.py`` (Phase 2C, 2026-06-05).

The original module concatenated this static system block with a dynamic
"User: Title: ... Source: ..." trailer per article. We migrate ONLY the static
block here so the worker keeps full control of dynamic field interpolation
(parameter set is therefore intentionally empty).

Versioning:
- ``version="1.0"`` matches the legacy ``_RELEVANCE_PROMPT_VERSION = "v1"``
  marker stored in ``document_source_llm_scores.prompt_version`` so existing
  rows remain attributable to the same prompt lineage.
"""

from __future__ import annotations

from prompts._base import PromptTemplate

# Identical wording to the in-worker constant — DO NOT edit without bumping
# version + content_hash (the latter is auto-computed). Any change here changes
# scoring semantics and breaks score-comparability across the ledger.
ARTICLE_RELEVANCE_SCORER = PromptTemplate(
    name="article_relevance_scorer",
    version="1.0",
    description=(
        "Static system block instructing an LLM to rate market-impact of a news "
        "article on a 0.0-1.0 scale and classify sentiment as "
        "positive/negative/neutral/mixed. Used by ArticleRelevanceScoringWorker "
        "for both the Ollama (qwen3:0.6b) and DeepInfra (Qwen2.5-0.5B-Instruct) "
        "execution paths. Dynamic title/source trailer is appended at call "
        "site — that's why ``parameters`` is empty."
    ),
    template=(
        "You are a financial news relevance assessor. "
        "Rate the market impact of this news article from 0.0 to 1.0.\n"
        "0.0 = completely irrelevant (celebrity news, sports, weather)\n"
        "0.3 = mildly relevant (broad economy, far sector)\n"
        "0.6 = moderately relevant (sector news, indirect exposure)\n"
        "0.9 = highly relevant (direct earnings, M&A, regulatory action)\n"
        "1.0 = critical (halted trading, major earnings miss, bankruptcy)\n"
        "If the title is absent, vague, or ambiguous, return score 0.3 as a conservative default.\n"
        "Also classify the market sentiment: "
        '"positive" (good news for investors), '
        '"negative" (bad news for investors), '
        '"neutral" (factual/no clear direction), '
        '"mixed" (contains both positive and negative signals).\n'
        "Respond with ONLY valid JSON: "
        '{{"score": <float 0.0-1.0>, "reason": "<max 10 words in English>", '
        '"sentiment": "positive"|"negative"|"neutral"|"mixed"}}'
    ),
    # No template parameters — the worker still appends the dynamic
    # "\nUser: Title: ...\nSource: ..." suffix itself (preserves byte-exact
    # parity with the legacy prompt and keeps the system/user split correct
    # for the DeepInfra chat-completions path).
    parameters=frozenset(),
)
