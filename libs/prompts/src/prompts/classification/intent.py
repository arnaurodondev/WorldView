"""Intent classification prompt template migrated from S8 rag-chat.

Used by ``OllamaIntentClassifier`` and ``DeepInfraIntentClassifier`` in
``rag_chat.application.pipeline.intent_classifier`` to classify a user query
into one of eight ``QueryIntent`` values.

Version history:
- 1.x — original 8-intent classifier, basic examples.
- 2.0 — PLAN-0061 Wave D rewrite with priority-ordered classification rules
  and richer per-intent examples (CEO/relationship/screening etc.).
- 2.1 — PLAN-0104 Wave 49 + F-NEW-014 (consolidation 2026-06-05): adds
  bare-ratio (P/E), margin trend, YoY growth, market-cap / EV examples so
  the LLM no longer mis-routes them to GENERAL. Folds the previously-inline
  ``_CLASSIFICATION_PROMPT`` body from ``intent_classifier.py`` into the
  shared template — single source of truth.
"""

from __future__ import annotations

from prompts._base import PromptTemplate

# WHY a single merged template:
# Prior to consolidation, ``classification/intent.py`` held the v2.0 priority
# rules and ``intent_classifier.py`` carried a parallel inline copy that had
# drifted forward with W49 / F-NEW-014 examples. Two copies meant any prompt
# tweak would silently disagree at runtime — exactly the drift that
# ``content_hash`` exists to catch. v2.1 merges both.
INTENT_CLASSIFICATION = PromptTemplate(
    name="intent_classification",
    # Bumping MINOR (not PATCH): we added new behaviour-relevant examples that
    # the model will measurably react to. Hash changes regardless, but the
    # version bump makes the change visible in dashboards.
    version="2.1",
    description="Classify user query into one of 8 financial intelligence intents",
    template=(
        "You are a query intent classifier for a financial intelligence system.\n"
        "Classify the query into exactly one of: FACTUAL_LOOKUP, RELATIONSHIP, SIGNAL_INTEL,\n"
        "FINANCIAL_DATA, COMPARISON, REASONING, PORTFOLIO, GENERAL.\n"
        "\n"
        "CLASSIFICATION RULES (apply in priority order — highest wins on ties):\n"
        "Priority: FINANCIAL_DATA > FACTUAL_LOOKUP > SIGNAL_INTEL > REASONING"
        " > COMPARISON > RELATIONSHIP > PORTFOLIO > GENERAL\n"
        "1. FINANCIAL_DATA: query requests specific numerical metrics (price, ratio,"
        " EPS, revenue, P/E, EV/EBITDA, yield, percentage, market cap, EV, shares"
        " outstanding, book value, net debt, beta, ROIC, float, margins, FCF, growth)."
        " Wins over all other intents.\n"
        "2. FACTUAL_LOOKUP: query asks for a specific named-entity fact (CEO, headquarters,"
        " founding date, product line) that is not primarily numerical.\n"
        "3. SIGNAL_INTEL: query asks for recent news, events, or market signals for an entity."
        " Use for ambiguous follow-up questions about a previously-mentioned entity.\n"
        "4. REASONING: query asks 'why' or 'how' and requires causal explanation."
        " Rephrase as a standalone question using conversation context.\n"
        "5. COMPARISON: query mentions two or more entities for side-by-side analysis."
        " Extract sub_questions (one per entity).\n"
        "6. RELATIONSHIP: query asks how two entities are connected.\n"
        "7. PORTFOLIO: query references the user's own holdings, watchlist, or portfolio risk.\n"
        "8. GENERAL: ambiguous, educational, or open-ended questions not tied to a specific"
        " entity or financial metric.\n"
        "\n"
        "Examples:\n"
        '- "Who is Apple\'s CEO?" ->'
        ' {{"intent":"FACTUAL_LOOKUP","sub_questions":[],'
        '"rephrased_query":"Who is the CEO of Apple Inc.?"}}\n'
        '- "Why is Apple\'s margin declining?" ->'
        ' {{"intent":"REASONING","sub_questions":[],'
        '"rephrased_query":"Why is Apple\'s gross margin declining?"}}\n'
        '- "Compare TSLA vs RIVN margins" ->'
        ' {{"intent":"COMPARISON","sub_questions":["What are Tesla\'s margins?",'
        '"What are Rivian\'s margins?"],"rephrased_query":"Compare TSLA and RIVN margins."}}\n'
        '- "What risks affect my holdings?" ->'
        ' {{"intent":"PORTFOLIO","sub_questions":[],'
        '"rephrased_query":"What risks affect my portfolio holdings?"}}\n'
        '- "What is Apple\'s relationship with TSMC?" ->'
        ' {{"intent":"RELATIONSHIP","sub_questions":[],'
        '"rephrased_query":"What is Apple\'s supply chain relationship with TSMC?"}}\n'
        '- "Latest news on Nvidia?" ->'
        ' {{"intent":"SIGNAL_INTEL","sub_questions":[],'
        '"rephrased_query":"What are recent news and announcements about Nvidia?"}}\n'
        '- "What is TSLA\'s current P/E ratio?" ->'
        ' {{"intent":"FINANCIAL_DATA","sub_questions":[],'
        '"rephrased_query":"What is Tesla\'s current price-to-earnings ratio?"}}\n'
        # PLAN-0104 W49: bare-ratio / margin / cash-flow / growth questions about a
        # specific entity MUST classify as FINANCIAL_DATA so the snapshot/history
        # toolchain fires and the 4-section ANSWER STRUCTURE addendum is included.
        "- \"What's AAPL's P/E ratio?\" ->"
        ' {{"intent":"FINANCIAL_DATA","sub_questions":[],'
        '"rephrased_query":"What is Apple\'s current P/E ratio?"}}\n'
        '- "Show me Meta\'s EPS over the last 4 quarters." ->'
        ' {{"intent":"FINANCIAL_DATA","sub_questions":[],'
        '"rephrased_query":"What is Meta\'s diluted EPS for the last 4 quarters?"}}\n'
        "- \"What's Amazon's YoY revenue growth?\" ->"
        ' {{"intent":"FINANCIAL_DATA","sub_questions":[],'
        '"rephrased_query":"What is Amazon\'s year-over-year revenue growth?"}}\n'
        '- "How has Tesla\'s gross margin trended in the last year?" ->'
        ' {{"intent":"FINANCIAL_DATA","sub_questions":[],'
        '"rephrased_query":"What is Tesla\'s gross margin trend over the trailing four quarters?"}}\n'
        # F-NEW-014: size & capital structure category (market cap, EV, shares
        # outstanding, book value, net debt, beta, ROIC, float) routes to FINANCIAL_DATA.
        '- "What is Apple\'s market capitalization?" ->'
        ' {{"intent":"FINANCIAL_DATA","sub_questions":[],'
        '"rephrased_query":"What is Apple\'s current market capitalization?"}}\n'
        '- "What about AAPL?" ->'
        ' {{"intent":"SIGNAL_INTEL","sub_questions":[],'
        '"rephrased_query":"What are the latest news and signals for Apple Inc.?"}}\n'
        '- "How do interest rates affect stock prices?" ->'
        ' {{"intent":"GENERAL","sub_questions":[],'
        '"rephrased_query":"How do interest rate changes affect equity valuations?"}}\n'
        "\n"
        "Query: {message}\n"
        "Conversation context: {history}\n"
        "Resolved entities: {entities}\n"
        "Respond with JSON only — valid JSON, no markdown, no code fences:"
        ' {{"intent": "...", "sub_questions": [...], "rephrased_query": "..."}}\n'
    ),
    parameters=frozenset({"message", "history", "entities"}),
)

__all__ = ["INTENT_CLASSIFICATION"]
