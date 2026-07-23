#!/usr/bin/env python3
"""DB session-bootstrap parity checker (BP-732 automated backstop).

Three independent hardening passes (`bea446831`, `0d0f27119`, `f1d04b8e5`)
each landed a Postgres connection-hardening lesson in only the service(s)
in front of the incident that motivated them, because every service used to
hand-roll its own ``connect_args`` in its own `infrastructure/<db>/session.py`.
The BP-732 fix extracts a shared `messaging.pg.engine_factory.build_async_engine`
factory so new hardening lands once — but a service can still opt out of the
factory (or a future service can be scaffolded without it), silently
regressing to the "duplicated, drifting connect_args" state this refactor
was meant to end.

This script is the automated backstop: it finds every `infrastructure/*/session.py`
file under `services/` (covering the plain `infrastructure/db/session.py` layout
most services use AND the dual-database `infrastructure/nlp_db/session.py` /
`infrastructure/intelligence_db/session.py` layout nlp-pipeline and
knowledge-graph use), classifies each as PgBouncer-pooled or direct based on
either (a) the literal hand-rolled `statement_cache_size` marker, or (b) a call
into the shared factory with `pooled=True` — then WARNS (or, with ``--strict``,
FAILS) if a pooled file is missing a `command_timeout`/`statement_timeout`
hardening knob that ANOTHER pooled file already has.

It intentionally does not try to determine "is this service pooled" from any
source other than the codebase itself (there is no infra-topology manifest in
this repo — that lives in a private gitops repo) — the same two signals the
2026-07-23 audit used to build its service/hardening table.

Usage:
    python scripts/check_db_session_parity.py            # warn-only (exit 0)
    python scripts/check_db_session_parity.py --strict    # fail (exit 1) on any gap

Exit codes:
    0 = no parity gaps found (or --strict not passed)
    1 = --strict passed AND at least one pooled session file is missing a knob
        another pooled session file already has
    2 = script error (no session files found at all — likely a path/glob bug)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICES_DIR = os.path.join(REPO_ROOT, "services")

# Literal-text signals checked against each session-bootstrap file's source.
# `_POOLED_MARKER` (hand-rolled connect_args) and `_POOLED_FACTORY_CALL_RE`
# (delegated to the shared BP-732 factory) are two INDEPENDENT ways a file can
# prove it is PgBouncer-pooled — a file only needs one to count as pooled.
_POOLED_MARKER = "statement_cache_size"
_POOLED_FACTORY_CALL_RE = re.compile(r"pooled\s*=\s*True")
_COMMAND_TIMEOUT_MARKER = "command_timeout"
_STATEMENT_TIMEOUT_MARKER = "statement_timeout"

# A file that calls the shared `build_async_engine()` factory (BP-732) gets
# both timeout knobs applied by the factory's own non-zero DEFAULTS even if
# the file's own source text never spells out the words "command_timeout" /
# "statement_timeout" anywhere except a comment. Reviewer A (2026-07-23 review
# of this exact script) correctly flagged that relying SOLELY on a literal
# substring match is fragile — a future comment reflow/removal on a
# factory-migrated file would silently misreport full compliance as a gap.
# So: a file that calls `build_async_engine(` counts as having a knob UNLESS
# it explicitly opts out via `command_timeout_s=0` / `statement_timeout_ms=0`
# (the factory's own documented "0 disables it" contract).
_BUILD_FACTORY_CALL_RE = re.compile(r"build_async_engine\s*\(")
_COMMAND_TIMEOUT_OPT_OUT_RE = re.compile(r"command_timeout_s\s*=\s*0(?!\.\d)\b")
_STATEMENT_TIMEOUT_OPT_OUT_RE = re.compile(r"statement_timeout_ms\s*=\s*0\b")


@dataclass
class SessionFileStatus:
    service: str
    path: str
    pooled: bool
    has_command_timeout: bool
    has_statement_timeout: bool
    missing: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.pooled and not self.has_command_timeout:
            self.missing.append("command_timeout")
        if self.pooled and not self.has_statement_timeout:
            self.missing.append("statement_timeout")

    @property
    def label(self) -> str:
        """Short display label distinguishing multiple session files per service."""
        rel = os.path.relpath(self.path, os.path.join(SERVICES_DIR, self.service, "src"))
        # Drop the redundant .../infrastructure/<x>/session.py -> just "<x>"
        # e.g. "nlp_pipeline/infrastructure/nlp_db/session.py" -> "nlp_db"
        parts = rel.split(os.sep)
        try:
            idx = parts.index("infrastructure")
            db_name = parts[idx + 1]
        except (ValueError, IndexError):
            db_name = "db"
        return f"{self.service} ({db_name})"


def _find_session_files() -> dict[str, list[str]]:
    """Map service name -> list of session-bootstrap file paths under it.

    Matches ANY file at `.../infrastructure/<anything>/session.py` — not just
    the plain `infrastructure/db/session.py` layout — so dual-database
    services (nlp-pipeline: nlp_db + intelligence_db; knowledge-graph:
    intelligence_db) are picked up instead of being misreported as
    "unmatched" (they were only unmatched by BP-732's original path-glob
    check, which assumed a single `infrastructure/db/` layout).
    """
    found: dict[str, list[str]] = {}
    if not os.path.isdir(SERVICES_DIR):
        return found
    session_path_re = re.compile(
        re.escape(os.sep)
        + r"infrastructure"
        + re.escape(os.sep)
        + r"[^"
        + re.escape(os.sep)
        + r"]+"
        + re.escape(os.sep)
        + r"session\.py$"
    )
    for service in sorted(os.listdir(SERVICES_DIR)):
        service_dir = os.path.join(SERVICES_DIR, service)
        src_dir = os.path.join(service_dir, "src")
        if not os.path.isdir(src_dir):
            continue
        matches: list[str] = []
        for root, _dirs, files in os.walk(src_dir):
            if "session.py" not in files:
                continue
            candidate = os.path.join(root, "session.py")
            if session_path_re.search(candidate):
                matches.append(candidate)
        if matches:
            found[service] = sorted(matches)
    return found


def _classify(service: str, path: str) -> SessionFileStatus:
    """Classify one session-bootstrap file's hardening markers.

    Reads the file's SOURCE CODE only (never a runtime DSN, credential, or
    config value) — the only things ever printed back to stdout are boolean
    presence/absence markers and the file's relative path/label, so this
    script cannot leak a secret even if a `session.py` somehow had one
    hardcoded (which R8/CLAUDE.md's "no secrets in code" rule forbids anyway).
    """
    with open(path, encoding="utf-8") as f:
        text = f.read()
    pooled = _POOLED_MARKER in text or bool(_POOLED_FACTORY_CALL_RE.search(text))
    calls_shared_factory = bool(_BUILD_FACTORY_CALL_RE.search(text))

    has_command_timeout = _COMMAND_TIMEOUT_MARKER in text or (
        calls_shared_factory and not _COMMAND_TIMEOUT_OPT_OUT_RE.search(text)
    )
    has_statement_timeout = _STATEMENT_TIMEOUT_MARKER in text or (
        calls_shared_factory and not _STATEMENT_TIMEOUT_OPT_OUT_RE.search(text)
    )

    return SessionFileStatus(
        service=service,
        path=path,
        pooled=pooled,
        has_command_timeout=has_command_timeout,
        has_statement_timeout=has_statement_timeout,
    )


def _find_unmatched_services(matched_services: set[str]) -> list[str]:
    """Services with a src/ dir but NO infrastructure/*/session.py at all.

    BP-732's audit found content-ingestion and portfolio in this bucket —
    later confirmed (BUG_PATTERNS.md BP-732, citing `bea446831`) to be an
    intentional architectural difference: both stay on DIRECT connections,
    never PgBouncer, because of session-scoped AGE/advisory-lock state, not a
    gap. This function still reports the bucket every run so a FUTURE
    unmatched service is surfaced for a human to classify, rather than
    assumed to be another instance of the already-explained exception.
    """
    unmatched: list[str] = []
    if not os.path.isdir(SERVICES_DIR):
        return unmatched
    for service in sorted(os.listdir(SERVICES_DIR)):
        service_dir = os.path.join(SERVICES_DIR, service)
        if not os.path.isdir(service_dir) or not os.path.isdir(os.path.join(service_dir, "src")):
            continue
        if service not in matched_services:
            unmatched.append(service)
    return unmatched


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any pooled session file is missing a hardening knob another pooled file has.",
    )
    args = parser.parse_args()

    session_files = _find_session_files()
    if not session_files:
        print("ERROR: no infrastructure/*/session.py files found under services/ — path glob is likely stale.")
        return 2

    statuses: list[SessionFileStatus] = []
    for service, paths in sorted(session_files.items()):
        statuses.extend(_classify(service, path) for path in paths)

    pooled_statuses = [s for s in statuses if s.pooled]
    unpooled_statuses = [s for s in statuses if not s.pooled]
    unmatched = _find_unmatched_services(set(session_files))

    pooled_with_command_timeout = [s.label for s in pooled_statuses if s.has_command_timeout]
    pooled_with_statement_timeout = [s.label for s in pooled_statuses if s.has_statement_timeout]

    print("=== DB session-bootstrap parity check (BP-732) ===\n")
    print(f"{'session file':<32} {'pooled':<8} {'command_timeout':<17} {'statement_timeout':<18}")
    for s in statuses:
        print(
            f"{s.label:<32} {('yes' if s.pooled else 'n/a'):<8} "
            f"{('present' if s.has_command_timeout else 'absent'):<17} "
            f"{('present' if s.has_statement_timeout else 'absent'):<18}"
        )

    gaps = [s for s in pooled_statuses if s.missing]

    print()
    if gaps:
        print("PARITY GAPS (pooled session file missing a knob another pooled file already has):")
        for s in gaps:
            for missing_knob in s.missing:
                proof = (
                    pooled_with_command_timeout if missing_knob == "command_timeout" else pooled_with_statement_timeout
                )
                proof_str = ", ".join(proof) if proof else "no other pooled file yet — flagged for awareness"
                print(f"  - {s.label}: missing {missing_knob} (already present in: {proof_str})")
    else:
        print("No parity gaps among pooled session files.")

    if unpooled_statuses:
        print(
            f"\nDirect-connection session files (no PgBouncer signal — excluded from the "
            f"pooled-parity check): {', '.join(s.label for s in unpooled_statuses)}"
        )

    if unmatched:
        print(
            f"\nServices with no infrastructure/*/session.py at all (as of BP-732 this is a KNOWN, "
            f"confirmed-intentional architectural difference for content-ingestion/portfolio — both "
            f"stay on direct connections because of session-scoped AGE/advisory-lock state; a NEW "
            f"entry here should be investigated, not assumed benign): {', '.join(unmatched)}"
        )

    print()
    if gaps and args.strict:
        print(
            f"FAIL: {len(gaps)} pooled session file(s) have a parity gap (see above). Re-run without --strict to warn only."
        )
        return 1
    if gaps:
        print(
            f"WARN: {len(gaps)} pooled session file(s) have a parity gap (see above). Pass --strict to fail CI on this."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
