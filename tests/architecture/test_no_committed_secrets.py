"""CI guard: no secret-bearing env files may be committed to the repo.

A real secret-laden ``services/knowledge-graph/configs/docker.env.bak`` was once
committed because (a) the ``.bak`` suffix slipped past the ``*.env`` .gitignore
patterns and (b) the commit used ``git commit --no-verify``, bypassing the
``secret-scan`` pre-commit hook. Pre-commit hooks are advisory (any ``--no-verify``
defeats them); this test is the ENFORCED backstop — it runs in the Architecture
Tests CI job, which cannot be skipped, so a tracked env/secret file fails the build.

It checks the set of git-TRACKED files (not the working tree), so it catches a
secret file no matter how it was added. Templates (``*.env.example`` /
``*.env.template``) are the only env files allowed in the tree.
"""

from __future__ import annotations

import math
import re
import subprocess
from collections import Counter
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Files that legitimately live in the tree even though their name matches an env
# pattern: they are committed TEMPLATES with placeholder values, not real secrets.
_ALLOWED_SUFFIXES = (".env.example", ".env.template", ".env.sample")

# Tracked-file paths matching any of these (case-insensitive) are forbidden — they
# are real env files, backups, or key material that must never be committed.
_FORBIDDEN_PATTERNS = (
    r"/docker\.env$",  # the live, secret-filled service env
    r"\.env\.bak$",  # docker.env.bak — the exact incident
    r"\.env\.local$",
    r"\.env\.prod$",
    r"\.env\.production$",
    r"/configs/.*\.env\.[^/]+$",  # any configs/*.env.<suffix> (except allowed templates)
    r"\.bak$",  # editor/CLI backup copies (often clone a secret source)
    r"\.orig$",
    r"\.pem$",
    r"\.p12$",
    r"\.pfx$",
    r"(^|/)id_rsa$",
    r"(^|/)id_dsa$",
    r"\.keytab$",
)

# Secret-VALUE patterns to scan for inside any tracked text file (defence in depth:
# catches a secret pasted into a .py/.yaml/.md, not just a misnamed env file).
_VALUE_PATTERNS = {
    "openai/deepinfra-sk": re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    "anthropic-sk": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{40,}"),
    "github-pat": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}"),
    "aws-akid": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "google-api": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "slack-token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "stripe-sk": re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{24,}"),
}

# Generic provider-agnostic catch: a secret-NAMED assignment with a high-entropy
# value. This is what the original docker.env.bak DeepInfra/EODHD keys were —
# bare alphanumeric (no provider prefix), so the prefix patterns above miss them.
# The LHS must look like a secret to keep false-positives low; the value allows
# the EODHD ``<hex>.<digits>`` shape (the dot would otherwise truncate it < 16).
_GENERIC_SECRET_ASSIGN = re.compile(
    r"(?:API[_-]?KEY|SECRET[_-]?KEY|ACCESS[_-]?KEY|CLIENT[_-]?SECRET|PRIVATE[_-]?KEY"
    r"|AUTH[_-]?KEY|[_-]SECRET|[_-]TOKEN|PASSWORD)"
    r"['\"]?\s*[=:]\s*['\"]?([A-Za-z0-9_+/=.\-]{16,})",
    re.IGNORECASE,
)
# Values that are obviously NOT real secrets — placeholders, env-var indirection,
# dev defaults, or a code expression that READS a secret (settings.x / process.env.x)
# rather than a literal. Keeps the generic config-file scan near-zero false positive.
_PLACEHOLDER = re.compile(
    r"(your[_-]?|change[_-]?me|placeholder|example|dummy|sample|xxx|\.\.\.|<.*>"
    r"|\$\{|here$|todo|fixme|none|null|true|false|minioadmin|^postgres$|^dev[_-]"
    r"|process\.|settings\.|os\.environ|getenv|import\.meta|self\.|config\.|cls\."
    r"|^0+$|^x+$)",
    re.IGNORECASE,
)

# The generic ``NAME=<value>`` scan runs ONLY on config-ish files. Elsewhere (source,
# tests, docs) it floods on legit secret-handling CODE and mock fixtures; the hook's
# staged-diff scan + the provider-prefix patterns below cover those paths instead.
_CONFIG_SUFFIXES = (
    ".env",
    ".yaml",
    ".yml",
    ".toml",
    ".tfvars",
    ".conf",
    ".ini",
    ".properties",
)
_CONFIG_HINTS = ("/configs/", "/infra/", "docker-compose", "dockerfile")


def _is_config_file(path: str) -> bool:
    if any(seg in f"/{path}".lower() for seg in ("/tests/", "/__tests__/", "/e2e/")):
        return False
    low = path.lower()
    return low.endswith(_CONFIG_SUFFIXES) or any(h in low for h in _CONFIG_HINTS)


# Binary/large/vendored paths we skip when content-scanning (keeps the test fast).
_SKIP_CONTENT_DIRS = ("node_modules/", "/dist/", "/build/", ".git/")
_SKIP_CONTENT_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".pdf",
    ".ico",
    ".woff",
    ".woff2",
    ".lock",
    ".sqlite",
    ".min.js",
)


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


_TRACKED = _tracked_files()


def test_no_secret_or_env_files_are_tracked() -> None:
    """No real env file / backup / key material may be a tracked path."""
    forbidden = [re.compile(p, re.IGNORECASE) for p in _FORBIDDEN_PATTERNS]
    violations: list[str] = []
    for path in _TRACKED:
        if path.endswith(_ALLOWED_SUFFIXES):
            continue
        if any(rx.search(path) for rx in forbidden):
            violations.append(path)
    assert not violations, (
        "Secret-bearing / env / backup files are committed (remove them, add to "
        ".gitignore, and ROTATE any exposed credentials):\n  " + "\n  ".join(sorted(violations))
    )


def test_no_secret_values_in_tracked_text_files() -> None:
    """No high-signal secret token may appear inside any tracked text file."""
    violations: list[str] = []
    for path in _TRACKED:
        if path.endswith(_ALLOWED_SUFFIXES) or path.endswith(_SKIP_CONTENT_SUFFIXES):
            continue
        if any(d in f"/{path}" for d in _SKIP_CONTENT_DIRS):
            continue
        # This test file itself defines the regexes — skip it.
        if path.endswith("tests/architecture/test_no_committed_secrets.py"):
            continue
        fp = _REPO_ROOT / path
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except (OSError, ValueError):
            continue
        # Scan per-line so an inline ``# pragma: allowlist-secret`` allowlists only
        # that one line (e.g. a verified fake key in a redaction test) — never the
        # whole file, which would blind us to a real secret added later.
        is_config = _is_config_file(path)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "pragma: allowlist-secret" in line:
                continue
            hit = None
            # Provider-prefixed keys are high-signal — scan every file.
            for name, rx in _VALUE_PATTERNS.items():
                if rx.search(line):
                    hit = name
                    break
            # The generic NAME=<literal> form only on config files (low false-positive).
            if hit is None and is_config:
                m = _GENERIC_SECRET_ASSIGN.search(line)
                if m and not _PLACEHOLDER.search(m.group(1)):
                    hit = "generic-secret-assignment"
            if hit is not None:
                violations.append(f"{path}:{lineno}  ({hit})")
    assert not violations, (
        "Secret-looking tokens found in tracked files (remove + ROTATE; add "
        "'# pragma: allowlist-secret' only for verified non-secrets):\n  " + "\n  ".join(sorted(violations))
    )


# ---------------------------------------------------------------------------
# Hardcoded API-key detector (extends the env-file guard to ALL source files)
# ---------------------------------------------------------------------------
# Incident 2026-07-03: two REAL provider keys (EODHD + Finnhub) were pasted into
# ``libs/observability/tests/test_logging.py`` and pushed. The env-file guard
# above never looked inside ``.py`` files, so it missed them (GitGuardian caught
# them post-push). This detector closes that gap for every tracked text file.
#
# Design goal: HIGH precision (zero false positives on a repo full of git SHAs,
# UUIDs, base64 fixtures, example JWTs, and storage keys) while still catching
# real provider/secret formats. Modelled on detect-secrets/gitleaks rules but
# dependency-free (pure ``re`` + ``git ls-files``) so it runs in the Architecture
# Tests CI job. Two layers:
#   1. High-confidence PROVIDER prefixes (AWS/OpenAI/GitHub/Google/Slack/Stripe/
#      EODHD + PEM private-key blocks) — scanned in every file.
#   2. A GENERIC ``<secret-named-var> = "<literal>"`` catch for prefix-less keys
#      (Finnhub/DeepInfra bare alnum), PLUS a URL-query form (``?token=<key>`` —
#      the exact Finnhub vector). Suppressed unless the value looks like a real
#      random token: contiguous alnum, contains a digit, high Shannon entropy,
#      and not a placeholder/dictionary word / example JWT.
# Escape hatch: an inline ``# pragma: allowlist secret`` (or ``allowlist-secret``)
# allowlists a single verified-fake line.

# Layer 1 — provider-prefixed / structural secret formats (very low FP rate).
_SOURCE_PROVIDER_PATTERNS = {
    "private-key-block": re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    "aws-akia": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "openai-sk": re.compile(r"\bsk-(?!ant-)[A-Za-z0-9]{20,}\b"),
    "anthropic-sk": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{40,}"),
    "slack-token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    "github-pat": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{22,}"),
    "google-api": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    "stripe-sk": re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{24,}\b"),
    # EODHD ``<14 hex>.<8 digits>``; ``demo``-prefixed synthetic tokens excluded.
    "eodhd-token": re.compile(r"\b(?!demo)[0-9a-f]{14}\.[0-9]{8}\b"),
}

# Layer 2 — generic ``secret-named-var = "literal"`` (prefix-less bare keys).
_SOURCE_GENERIC_ASSIGN = re.compile(
    r"(?i)(?:[a-z0-9]{0,20}[_-])?"
    r"(?:api[_-]?key|apikey|secret[_-]?key|client[_-]?secret|access[_-]?key|"
    r"secret|api[_-]?token|auth[_-]?token|token|key|password|passwd|pwd)"
    r"['\"]?\s*[:=]\s*['\"]([A-Za-z0-9+=]{20,})['\"]"
)

# Layer 2b — a secret embedded in a URL query param (``?api_token=<key>``). This is
# the EXACT vector of the 2026-07-03 Finnhub leak (key pasted inside an httpx URL
# string). The value is unquoted, so the quoted-literal rule above misses it.
_SOURCE_URL_PARAM = re.compile(
    r"(?i)[?&](?:api[_-]?token|api[_-]?key|access[_-]?token|auth[_-]?token|token|"
    r"apikey|api[_-]?secret|secret|password)=([A-Za-z0-9]{16,})"
)

# Values containing any of these substrings are obvious non-secrets (placeholders,
# dev defaults, well-known dictionary words). Real random keys never contain them,
# so this is a safe suppressor.
_SOURCE_FAKE_WORDS = re.compile(
    r"(?i)(demo|example|test|dummy|fake|placeholder|replace|changeme|sample|mock|"
    r"invalid|definitely|todo|fixme|redacted|deepinfra|skipverif|yourkey|"
    r"masterkey|character|needsto)"
)

# Explicit path/substring ALLOWLIST for known-safe fixtures. Currently empty (the
# entropy/word heuristics already yield zero false positives) but wired so a future
# verified fixture can be exempted without weakening the detector globally.
_SOURCE_ALLOWLIST_GLOBS: tuple[str, ...] = ()


def _shannon_entropy(s: str) -> float:
    """Shannon entropy (bits/char) — random keys score high, words/repeats low."""
    n = len(s)
    if n == 0:
        return 0.0
    return -sum((c / n) * math.log2(c / n) for c in Counter(s).values())


def _looks_fake(value: str) -> bool:
    """True when *value* is clearly not a real secret (placeholder / low entropy)."""
    if _SOURCE_FAKE_WORDS.search(value):
        return True
    if "1234567890" in value or "abcdefghij" in value.lower():
        return True
    if re.search(r"(.)\1{4,}", value):  # 5+ identical consecutive chars (aaaaa, 00000)
        return True
    if _shannon_entropy(value) < 3.0:
        return True
    return False


def _find_hardcoded_secret(line: str) -> str | None:
    """Return the rule name if *line* contains a hardcoded secret, else None."""
    for name, rx in _SOURCE_PROVIDER_PATTERNS.items():
        m = rx.search(line)
        if m:
            # PEM headers are unambiguous; other prefixes still pass a fake filter
            # so obvious ``sk-1234567890...`` fixtures don't trip the build.
            if name == "private-key-block" or not _looks_fake(m.group(0)):
                return name
    m = _SOURCE_GENERIC_ASSIGN.search(line)
    if m:
        value = m.group(1)
        # Real bare tokens are contiguous alnum WITH a digit and high entropy.
        # Identifiers / enum values / storage keys lack a digit or are word-like;
        # dotted/pathy values never reach here (regex value class excludes ``.`` / ``/``).
        if value.startswith("eyJ"):  # example JWT header — not a bare secret
            return None
        if not re.search(r"\d", value):  # random keys carry digits; identifiers rarely
            return None
        if not _looks_fake(value):
            return "generic-secret-assignment"
    m = _SOURCE_URL_PARAM.search(line)
    if m:
        value = m.group(1)
        # Same discipline as the generic rule: a real key in a URL carries a digit,
        # is high-entropy, and isn't an example JWT / placeholder.
        if not value.startswith("eyJ") and re.search(r"\d", value) and not _looks_fake(value):
            return "url-query-secret"
    return None


def test_no_hardcoded_api_keys_in_source() -> None:
    """No hardcoded provider/secret token may appear in ANY tracked text file.

    This is the backstop that would have caught the 2026-07-03 EODHD/Finnhub
    leak (keys pasted into a ``.py`` test). It scans every tracked file, not just
    env/config files.
    """
    violations: list[str] = []
    for path in _TRACKED:
        if path.endswith(_ALLOWED_SUFFIXES) or path.endswith(_SKIP_CONTENT_SUFFIXES):
            continue
        if any(d in f"/{path}" for d in _SKIP_CONTENT_DIRS):
            continue
        if any(g in path for g in _SOURCE_ALLOWLIST_GLOBS):
            continue
        # This test file itself defines the patterns / positive-control samples.
        if path.endswith("tests/architecture/test_no_committed_secrets.py"):
            continue
        try:
            text = (_REPO_ROOT / path).read_text(encoding="utf-8", errors="ignore")
        except (OSError, ValueError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "pragma: allowlist secret" in line or "pragma: allowlist-secret" in line:
                continue
            hit = _find_hardcoded_secret(line)
            if hit is not None:
                violations.append(f"{path}:{lineno}  ({hit})  {line.strip()[:100]}")
    assert not violations, (
        "Hardcoded API keys / secrets found in tracked source files. If REAL: "
        "remove + ROTATE the credential. If a verified fake (e.g. a redaction-test "
        "fixture): make it obviously synthetic or add '# pragma: allowlist secret' "
        "to that line.\n  " + "\n  ".join(sorted(violations))
    )


def test_secret_detector_catches_known_bad_samples() -> None:
    """Positive control: the detector MUST catch real-looking secret formats.

    Guards against the detector silently degrading (e.g. a regex edit that stops
    matching). All samples below are SYNTHETIC — not live credentials.
    """
    # Samples are assembled from FRAGMENTS at runtime so no literal secret appears in
    # this source file — otherwise the repo's own pre-commit secret-scan / detect-private-key
    # hooks (correctly) flag this very test file. The detector still receives the full string.
    _hex14 = "6a3b1c2d3e4f5a"
    _fin = "d7msqbpr01" + "qngrvpaoj9"
    must_catch = {
        "eodhd": 'EODHD_API_KEY = "' + _hex14 + "." + '12345678"',
        "finnhub-bare": 'finnhub_token = "' + _fin + '"',
        "finnhub-in-url": "GET https://finnhub.io/x?token=" + _fin + "&x=1",
        "deepinfra-bare": 'DEEPINFRA_API_KEY = "' + "K2wVkxAbc9QmZ7pL" + 'tY4bZ8hNqR7vWpLt"',
        "aws": 'aws_key = "' + "AKIA" + 'Z7QH8DJKLMNPQRST"',
        "openai": 'OPENAI_API_KEY = "' + "sk-" + 'proj9Xk2mNqR7vWpLtY4bZ8h"',
        "github": 'GITHUB_TOKEN = "' + "ghp_" + '16C7e42F292c6912E7710c838347Ae178B4a"',
        "google": 'key = "' + "AIza" + 'SyD9aBcEfGhIjKlMnOpQrStUvWxYz012345"',
        "rsa-pem": "-----BEGIN RSA " + "PRIVATE KEY-----",
        "openssh-pem": "-----BEGIN OPENSSH " + "PRIVATE KEY-----",
    }
    missed = [name for name, line in must_catch.items() if _find_hardcoded_secret(line) is None]
    assert not missed, f"Detector FAILED to catch known secret formats: {missed}"

    must_ignore = {
        "placeholder": 'api_key = "your-api-key-here-xxx"',
        "example-jwt": 'token = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxIn0.sig"',
        "git-sha": 'commit = "0a1dbab5e9f2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"',
        "env-read": 'api_key = os.getenv("DEEPINFRA_API_KEY")',
        "dev-key": 'internal_key = "dev-skip-verification-key-for-portfolio"',
        "storage-key": 'STORAGE_KEY = "worldview.preferences.v1"',
        "s3-ref": '"canonical_ref_key": "fundamentals/aapl.json"',
        "jwt-in-url": "ws://api-gateway:8000/api/v1/alerts/stream?token=eyJhbGciOiJSUzI1NiIs",
    }
    false_pos = [name for name, line in must_ignore.items() if _find_hardcoded_secret(line) is not None]
    assert not false_pos, f"Detector false-positived on known-safe samples: {false_pos}"
