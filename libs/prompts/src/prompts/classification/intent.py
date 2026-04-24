"""Intent classification prompt template migrated from S8 rag-chat (Wave A-2).

Used by ``OllamaIntentClassifier`` to classify user queries into one of
eight ``QueryIntent`` values via the local qwen2.5:3b model.
"""

from __future__ import annotations

from prompts._base import PromptTemplate

INTENT_CLASSIFICATION = PromptTemplate(
    name="intent_classification",
    version="2.0",
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
        " EPS, revenue, P/E, EV/EBITDA, yield, percentage). Wins over all other intents.\n"
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
        '- "How do interest rates affect stock prices?" ->'
        ' {{"intent":"GENERAL","sub_questions":[],'
        '"rephrased_query":"How do interest rate changes affect equity valuations?"}}\n'
        '- "What about AAPL?" ->'
        ' {{"intent":"SIGNAL_INTEL","sub_questions":[],'
        '"rephrased_query":"What are the latest news and signals for Apple Inc.?"}}\n'
        '- "What is Apple\'s CEO and current stock price?" ->'
        ' {{"intent":"FINANCIAL_DATA","sub_questions":[],'
        '"rephrased_query":"What is Apple\'s current stock price and CEO?"}}\n'
        "\n"
        "Query: {message}\n"
        "Conversation context: {history}\n"
        "Resolved entities: {entities}\n"
        "Respond with JSON only — valid JSON, no markdown, no code fences:"
        ' {{"intent": "...", "sub_questions": [...], "rephrased_query": "..."}}\n'
    ),
    parameters=frozenset({"message", "history", "entities"}),
)
