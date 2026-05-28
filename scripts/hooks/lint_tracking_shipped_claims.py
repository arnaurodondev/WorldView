#!/usr/bin/env python3
"""PLAN-0099 W4 T-W4-01 (audit §13.5): TRACKING.md SHIPPED-claim lint.

Phase-D code review §8 flagged a TRACKING.md row that claimed
``W3-SHIPPED <hash>`` before the hash was in ``git log``. This script
walks ``docs/plans/TRACKING.md`` and for each row that mentions a
commit hash inside a ``SHIPPED``/``shipped`` context asserts the hash
exists in the local git history.

The check is intentionally permissive:

* Only 7+ hex-char tokens that look like a git short-SHA after a
  ``shipped``/``ship``/``SHIPPED`` keyword are validated.
* Hashes that ``git rev-parse`` cannot resolve trigger an error.
* Unknown hashes are reported with line number so the operator can
  decide whether the claim is premature or the hash typo'd.

Exit codes:
    0 — every claim resolves cleanly.
    1 — one or more SHIPPED hashes are not in git history.

Run from repo root:

    python scripts/hooks/lint_tracking_shipped_claims.py

Pre-PR script invocation lives in the PLAN-0099 W4 compounding note.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Tracking file path is hard-coded — single canonical location.
TRACKING = Path(__file__).resolve().parent.parent.parent / "docs" / "plans" / "TRACKING.md"

# Match a "shipped" / "SHIPPED" / "ship " keyword followed within ~120
# chars by a *backtick-quoted* hash-looking token. The hash group
# accepts 7..40 hex.
#
# Why backticks-only: TRACKING.md uniformly quotes commit hashes with
# backticks (e.g. ``shipped commit `f0e4aace` ``). Matching bare hex
# substrings produced a torrent of false positives on English words
# that happen to be 7+ chars of [a-f] (e.g. "feedback" → "feedbac").
# The narrow form keeps the lint actionable without regressing on the
# years of historical rows.
_SHIPPED_HASH_RE = re.compile(
    r"(?:shipped|ship|SHIPPED)[^\n]{0,120}?`([0-9a-f]{7,40})`",
    re.IGNORECASE,
)


def _hash_exists(sha: str) -> bool:
    """Return True iff ``git rev-parse`` resolves ``sha`` to a commit."""
    # ``rev-parse --verify`` returns non-zero on unknown refs; capture
    # both streams to keep the lint output clean.
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{sha}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def main() -> int:
    if not TRACKING.exists():
        print(f"TRACKING.md not found at {TRACKING}", file=sys.stderr)
        return 1

    text = TRACKING.read_text(encoding="utf-8")
    errors: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in _SHIPPED_HASH_RE.finditer(line):
            sha = match.group(1)
            # Single-word filter: 7..40 hex. Skip pure-decimal IDs that
            # could match (e.g. years like "2026" never match because
            # the regex requires at least one alpha hex char to fall in
            # 7..40 -- but defensive: skip if no alpha char present).
            if not any(c in "abcdef" for c in sha):
                continue
            if not _hash_exists(sha):
                errors.append((lineno, sha))

    if errors:
        print("TRACKING.md SHIPPED-claim lint failed:", file=sys.stderr)
        for lineno, sha in errors:
            print(f"  TRACKING.md:{lineno}: unknown hash `{sha}`", file=sys.stderr)
        print(
            "\nA SHIPPED row must reference a hash present in `git log`. "
            "Either commit first, or fix the hash. See PLAN-0099 W4 T-W4-01.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
