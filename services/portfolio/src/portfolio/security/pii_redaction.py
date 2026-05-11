"""PII / secret redaction for user-submitted feedback (PLAN-0052 Wave D / T-D-4-04).

Why this module exists:
    User-submitted feedback (descriptions, NPS comments, micro-survey
    comments, captured console_logs) frequently contains accidentally
    leaked secrets — Bearer tokens copied from a network tab, the
    user's own API key in a curl example, an email address that should
    not land in the analytics warehouse.

    Redaction happens at the application layer (use case) BEFORE the
    text reaches the database. Once it's in Postgres there is no
    safe way to scrub it (downstream BI/ETL pipelines may have
    already copied it).

Pattern philosophy:
    All patterns are conservative — we'd rather over-redact than miss
    a real secret. False positives (e.g. redacting a non-token long
    alpha-numeric string) are a UX cost; false negatives (a secret in
    plaintext) are a security incident.

    Specifically the Bearer pattern is intentionally aggressive — any
    16+ char alphanumeric string after ``Bearer `` is redacted. Pages
    that legitimately contain Bearer-token examples (API docs, support
    walkthroughs) should expect over-redaction; rendering tooling that
    needs the literal example must escape the keyword (e.g. ``B&#x65;arer``)
    or move the example out of free-text fields. (F-Q1-10.)

    Each redaction replaces the matched substring with
    ``[REDACTED:<KIND>]`` where KIND identifies the pattern that
    fired. This keeps the redacted text readable to support staff
    while making it obvious what was scrubbed.

Idempotency:
    ``redact()`` is idempotent on already-redacted text — running it
    twice produces the same output. The replacement marker
    ``[REDACTED:KIND]`` does not match any of the regex patterns.
"""

from __future__ import annotations

import re
from typing import Any

# ── Compiled patterns (module-level for performance) ─────────────────────────
#
# Pattern order matters: more-specific patterns run first so a JWT does not
# get partially redacted as an "API key" before the JWT regex sees it. The
# Bearer regex preserves the "Bearer " prefix in the replacement so log
# readers can see "what kind of header was here" without learning the value.

# 1. JWT-like (three base64url segments, header looks like ``eyJ`` for "{...").
#    Run before Bearer because a raw JWT in a log line has no "Bearer " prefix.
_RE_JWT = re.compile(r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")

# 2. Bearer header pattern — covers ``Authorization: Bearer abc...`` and bare
#    ``Bearer abc...`` strings. We require at least 16 chars to avoid
#    redacting the literal word "Bearer" alone.
_RE_BEARER = re.compile(r"Bearer\s+[A-Za-z0-9_\-\.\=]{16,}")

# 3. API-key style assignments. Matches forms like:
#       api_key=ABCDEF...   api-key: "ABCDEF..."   API_KEY = ABCDEF...
#    Case-insensitive on the prefix; quotes are optional.
_RE_API_KEY = re.compile(
    r"""(?ix)                          # case-insensitive, verbose
    (api[_\-]?key)                     # group 1: the literal keyword
    [\s=:]+                            # separator (= : whitespace)
    ["']?                              # optional opening quote
    [A-Za-z0-9_\-]{16,}                # the secret itself
    ["']?                              # optional closing quote
    """,
)

# 4. Common header lines: authorization / x-api-key / cookie. We redact the
#    *value* not the header name so the log still shows which header leaked.
#    Header values may be multi-word (``Basic <b64>``, ``Bearer <jwt>``,
#    ``session=abc; other=def``) so we match through end-of-line / end-of-
#    string rather than a single non-whitespace token.
_RE_HEADER = re.compile(
    r"""(?ix)
    \b(authorization|x-api-key|cookie)
    :\s*
    [^\r\n]+                           # the header value (rest of line)
    """,
)

# 5. Email — common in error stacks, support pastes. We do NOT redact the
#    explicit ``email`` form field on the feedback submission itself; this
#    runs only against free-text fields (description / comments).
_RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

# 6. Credit-card-shaped 16-digit sequence. Catches ``4111-1111-1111-1111``
#    and ``4111 1111 1111 1111`` and ``4111111111111111``.
_RE_CC = re.compile(r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b")

# 7. US SSN-shaped string. Worldview is US-anchored; this is the highest-risk
#    PII pattern we have for the thesis demo.
_RE_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


# Order matters — see top-of-file comment.
_ORDERED_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_RE_JWT, "[REDACTED:JWT]"),
    # Bearer keeps the "Bearer " prefix so log readers see what kind of
    # header was scrubbed. The replacement still hides the secret itself.
    (_RE_BEARER, "Bearer [REDACTED:JWT]"),
    # API key replacement keeps the keyword (group 1) so the log line is
    # readable: ``api_key=[REDACTED:API_KEY]``. Without the back-reference
    # the redaction would lose context.
    (_RE_API_KEY, r"\1=[REDACTED:API_KEY]"),
    # Header replacement keeps the header name (group 1) for the same
    # readability reason as the API-key case above.
    (_RE_HEADER, r"\1: [REDACTED:HEADER]"),
    (_RE_EMAIL, "[REDACTED:EMAIL]"),
    (_RE_CC, "[REDACTED:CC]"),
    (_RE_SSN, "[REDACTED:SSN]"),
)


def redact(text: str | None) -> str | None:
    """Redact PII / secrets from a string.

    Returns ``None`` when input is ``None`` (so callers can pipe optional
    fields through without an extra branch). Empty strings round-trip as
    empty strings — no allocation, no regex pass.
    """
    if text is None:
        return None
    if not text:
        return text
    out = text
    for pattern, replacement in _ORDERED_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def redact_json(value: Any) -> Any:
    """Recursively redact strings inside a JSON-like structure.

    Why we walk the structure manually: the captured ``console_logs`` JSON
    payload is a list of log entries; each entry is a dict with a free-text
    ``message`` plus structured metadata. We can't just stringify the whole
    blob because that would destroy the JSON structure that the admin UI
    needs to render. Walking is O(N) and small N (≤50 entries by spec).

    Non-string scalars (numbers, bools, None) pass through untouched. Keys
    are left unredacted by design — log keys are usually field names like
    ``"timestamp"``/``"level"``/``"message"`` and not user-supplied.
    """
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [redact_json(item) for item in value]
    if isinstance(value, dict):
        return {k: redact_json(v) for k, v in value.items()}
    return value


__all__ = ["redact", "redact_json"]
