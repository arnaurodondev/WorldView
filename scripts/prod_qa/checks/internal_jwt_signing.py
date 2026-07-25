"""Internal-JWT signing-key completeness — LIVE cluster check (BP-752).

WHY THIS EXISTS: a live-cluster audit (2026-07-25) found ``portfolio`` and
``market-ingestion`` silently signing HS256 "dev fallback" internal JWTs in
production because their ``internal_jwt_private_key`` config value was
empty/unset in the DEPLOYED k8s Secret — while the internal APIs they call
(``market-data``) verify RS256 (``skip_verification=False`` is mandatory in
production) and reject HS256. Each caller degrades GRACEFULLY on the 401
(portfolio falls back to cost-basis pricing; market-ingestion falls back to
a static symbol universe) so nothing crashed and nothing paged — 24h+ of
100% silent auth failure with zero alerting.

This gap is a missing SECRET VALUE, not missing code — it cannot be caught
by a pytest architecture test running against the source tree (that's the
sibling ``tests/architecture/test_internal_jwt_signing_key_wiring.py``,
which catches the DIFFERENT "never wired up in code at all" class). This
check belongs here, in the live-cluster prod_qa suite, because answering
"is the key actually populated in the deployed Secret right now" requires
talking to the real cluster.

METHOD (BP-750 registry-completeness philosophy): don't hardcode a list of
"services that need this key" — that is exactly the hand-maintained-list
shape that let portfolio's gap go unenrolled in the first place. Instead,
independently RE-DERIVE the "should have this key populated" set by
filesystem-scanning every service's own ``config.py`` for an
``internal_jwt_private_key`` field (the same static signal the sibling
architecture test uses), then cross-check each such service's LIVE k8s
Secret for the corresponding env var KEY — checking only whether the key is
PRESENT and non-trivially long, never decoding/printing the value itself
(an RS256 PEM is always long; an absent key or an empty ``SecretStr("")``
env value both look "empty/short" here — either shape is the same
production bug).
"""

from __future__ import annotations

import re
from pathlib import Path

from .. import harness as H
from ..harness import Ctx

SVC = "internal_jwt_signing"

# scripts/prod_qa/checks/internal_jwt_signing.py -> repo root is 3 parents up.
REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICES_DIR = REPO_ROOT / "services"

# Matches a `Settings` class field named exactly `internal_jwt_private_key`
# (any annotation/default). Mirrors the AST scan in the sibling architecture
# test — kept as a regex here (not AST) because this module intentionally
# stays dependency-light/stdlib-only like the rest of the prod_qa harness
# (see harness.py's module docstring); a field-name regex is precise enough
# for this exact, single, already-established field name.
_FIELD_RE = re.compile(r"^\s*internal_jwt_private_key\s*:", re.MULTILINE)

# A real RS256 PEM key, base64-re-encoded by Kubernetes' Secret storage, is
# always well over a thousand characters. An absent key (jsonpath returns
# empty string) or a populated-but-empty `SecretStr("")` env var are both
# far shorter than this floor — either shape reproduces the same production
# bug (no real signing key available), so both are flagged identically.
_MIN_PLAUSIBLE_B64_LEN = 100


def _services_with_signing_key_field() -> list[str]:
    """Filesystem scan for every service whose config.py declares the field.

    Re-derives the "should be configured" set from source on every run,
    instead of a hand-maintained list of service names — see module
    docstring / BP-750.
    """
    found: list[str] = []
    if not SERVICES_DIR.is_dir():
        return found
    for svc_dir in sorted(SERVICES_DIR.iterdir()):
        if not svc_dir.is_dir():
            continue
        config_candidates = list(svc_dir.glob("src/*/config.py"))
        for config_py in config_candidates:
            try:
                text = config_py.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if _FIELD_RE.search(text):
                found.append(svc_dir.name)
                break
    return found


def _secret_env_var_name(service: str) -> str:
    """K8s Secret data-key naming convention for this field.

    Observed across every deployed secret during the BP-752 investigation:
    ``<SERVICE_NAME_UPPER_SNAKE>_INTERNAL_JWT_PRIVATE_KEY`` (e.g.
    ``KNOWLEDGE_GRAPH_INTERNAL_JWT_PRIVATE_KEY``, confirmed present live;
    ``PORTFOLIO_INTERNAL_JWT_PRIVATE_KEY`` / ``MARKET_INGESTION_INTERNAL_JWT_PRIVATE_KEY``,
    confirmed ABSENT live).
    """
    return f"{service.upper().replace('-', '_')}_INTERNAL_JWT_PRIVATE_KEY"


def run(ctx: Ctx) -> None:
    R = ctx.report
    services = _services_with_signing_key_field()
    if not services:
        R.warn(
            SVC,
            "internal_jwt_private_key field scan",
            "no services found with the field via filesystem scan — scan misconfigured, or repo layout changed?",
        )
        return

    for svc in sorted(services):
        secret_name = f"{svc}-secrets"
        env_key = _secret_env_var_name(svc)
        # Read ONLY the one data key's raw (still-base64) value — never
        # decoded — so this check never handles the real key material.
        _, raw_b64 = H.kubectl(f"-n {H.NS} get secret {secret_name} -o jsonpath='{{.data.{env_key}}}'")
        raw_b64 = raw_b64.strip().strip("'")
        populated = len(raw_b64) >= _MIN_PLAUSIBLE_B64_LEN
        R.check(
            SVC,
            f"{svc}: {env_key} populated in live Secret ({secret_name})",
            populated,
            (
                f"{len(raw_b64)} base64 chars present"
                if raw_b64
                else "key ABSENT from Secret — service is signing outbound internal JWTs "
                "with the HS256 dev fallback in production (BP-752)"
            ),
        )
