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

import re
import subprocess
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
