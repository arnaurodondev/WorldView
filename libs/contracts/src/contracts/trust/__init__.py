"""Trust authority constants for retrieval ranking (PLAN-0079)."""

from __future__ import annotations

SOURCE_AUTHORITY: dict[str, float] = {
    # SEC primary filings — highest authority
    # ``sec_edgar`` is the canonical literal the LIVE ingestion pipeline stamps on
    # every SEC filing (S4 EDGAR adapter → dsm.source_type). The per-form keys
    # below are OLD seed/fixture names the live pipeline never produces, so without
    # this entry every real filing fell through to ``default`` (0.50) instead of
    # top authority — a silent end-to-end taxonomy mismatch (R1 Fix ②).
    "sec_edgar": 1.00,
    "sec_10k": 1.00,
    "sec_10q": 1.00,
    "sec_8k": 0.95,
    # SEC amendments
    "sec_10k_a": 0.92,
    "sec_10q_a": 0.92,
    # Earnings transcripts
    "earnings_data": 0.92,
    "earnings_transcript": 0.92,
    # Corporate actions
    "corporate_action": 0.88,
    # Vetted wires (Reuters, Bloomberg, FT, WSJ)
    "press_release": 0.85,
    # Sell-side research
    "research": 0.80,
    # General news
    "eodhd_news": 0.65,
    "finnhub_news": 0.65,
    "newsapi": 0.65,
    # Knowledge graph derived
    "relation": 0.80,
    "claim": 0.75,
    "financial": 0.85,
    # Platform-curated narrative (LLM-generated entity summary)
    "narrative": 0.88,
    # Social/forum
    "social": 0.30,
    # User-generated
    "user_generated": 0.20,
    # Fallback
    "default": 0.50,
}

__all__ = ["SOURCE_AUTHORITY"]
