"""MinHash signature computation for near-duplicate detection.

Produces a 128-element integer signature from text using datasketch.
CRITICAL: Returns list[int], never numpy arrays — stored as INTEGER[] in Postgres.
"""

from __future__ import annotations

import re
import unicodedata

from datasketch import MinHash  # type: ignore[import-untyped]

# PRD §6.7 Block 2 — Financial stopwords for text normalization
FINANCIAL_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "for",
        "and",
        "nor",
        "but",
        "or",
        "yet",
        "so",
        "at",
        "by",
        "from",
        "in",
        "into",
        "of",
        "on",
        "to",
        "with",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        # Financial boilerplate
        "disclaimer",
        "forward-looking",
        "statements",
        "risks",
        "uncertainties",
        "copyright",
        "rights",
        "reserved",
        "press",
        "release",
        "contact",
    }
)


def normalize_financial_text(text: str) -> list[str]:
    """Normalize text for MinHash shingling.

    PRD §6.7 Block 2: NFC normalization, lowercase, strip punctuation,
    collapse whitespace, remove FINANCIAL_STOPWORDS + tokens <= 1 char.

    Args:
        text: Input text.

    Returns:
        List of tokens suitable for word-bigram generation.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    tokens = text.split()
    return [t for t in tokens if t not in FINANCIAL_STOPWORDS and len(t) > 1]


def compute_shingles(text: str) -> set[str]:
    """Compute union of word bigrams and char trigrams.

    PRD §6.7 Block 2:
    - Word bigrams: w:{t1}_{t2}
    - Char trigrams: c:{text[i:i+3]}

    Args:
        text: Input text (will be normalized internally).

    Returns:
        Set of shingle strings.
    """
    tokens = normalize_financial_text(text)

    # Word bigrams from normalized tokens
    word_bigrams = {f"w:{tokens[i]}_{tokens[i + 1]}" for i in range(len(tokens) - 1)}

    # Char trigrams from the original lowercased text (not the tokenized form)
    lower_text = text.lower()
    char_trigrams = {f"c:{lower_text[i:i + 3]}" for i in range(len(lower_text) - 2)}

    return word_bigrams | char_trigrams


def compute_minhash(text: str, num_perm: int = 128) -> list[int]:
    """Compute MinHash signature from text.

    CRITICAL: Returns list[int], not numpy array. Each element is a plain
    Python int. This is enforced by explicit conversion and assertion.

    Args:
        text: Input text to compute signature for.
        num_perm: Number of permutations (default 128).

    Returns:
        List of num_perm integer hash values.

    Raises:
        ValueError: If text produces no shingles.
    """
    shingles = compute_shingles(text)

    if not shingles:
        msg = "Text produced no shingles — cannot compute MinHash"
        raise ValueError(msg)

    m = MinHash(num_perm=num_perm)
    for s in shingles:
        m.update(s.encode("utf-8"))

    # CRITICAL: Convert numpy array to plain Python int list
    result = [int(v) for v in m.hashvalues]

    # Mandatory type assertion (plan requirement)
    assert len(result) == num_perm
    assert all(isinstance(v, int) for v in result)

    return result
