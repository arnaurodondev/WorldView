"""PROBES-completeness architecture test (closes the reactive-only-fix gap).

``synthetic_monitor.PROBES`` currently contains ``probe_deepinfra_key`` and
``probe_eodhd_key`` — both added AFTER a production incident (a silent
DeepInfra key rotation that killed the ML pipeline with no alert; the same
fragility class for EODHD). Every OTHER shared/rotatable external API key
configured across the platform (Finnhub, Polygon, Alpha Vantage, Alpaca,
Cohere, Jina, Gemini, OpenRouter, SnapTrade, …) has NO freshness probe today —
the exact same silent-death class is still live for all of them, just waiting
for its own incident to get noticed.

This test closes that gap by construction rather than by incident: it
independently re-derives "every config.py Settings field that looks like a
shared external API credential" via AST scan (the same technique
``tests/architecture/test_model_registry_completeness.py`` uses for the
model-registry side of this exact bug family), then asserts every one of them
is EITHER:

  1. covered by a matching ``probe_<name>_key`` function already registered in
     ``synthetic_monitor.PROBES`` (derived by stripping the field's
     "_api_key"/"_secret_key"/"_access_key"/"_consumer_key"/"_client_id"/
     "_client_secret"/"_key"/"_secret" suffix), OR
  2. explicitly exempted in ``infra/synthetic/_external_api_key_probe_allowlist.yaml``
     with a dated, reviewable justification (mirrors
     ``tests/architecture/_consumer_dedup_allowlist.yaml``'s pattern).

A brand-new key-shaped field that lands in neither bucket FAILS this test
loudly — forcing the same "add a probe" vs. "document why not" call to be
made explicitly, instead of silently doing neither until the next incident.

Deliberately scans BOTH ``SecretStr`` and plain ``str`` annotations (not
SecretStr alone): several genuinely-shared external keys in this repo are
typed plain ``str`` (e.g. ``alert.resend_api_key``, ``alert.sendgrid_api_key``,
``content-ingestion.eodhd_api_key``, ``libs/ml-clients``'s
``router_embedding_api_key``) — restricting to SecretStr would silently miss
exactly the fields this test exists to catch (an earlier draft of this test
did that and missed ``portfolio.snaptrade_secret_encryption_key`` entirely
until an independent review caught it). The credential-shaped NAME regex is
what does the real filtering work here, not the type annotation.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest
import yaml  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit

# infra/synthetic/tests/ -> infra/synthetic/ -> infra/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICES_DIR = REPO_ROOT / "services"
_MONITOR_PATH = Path(__file__).resolve().parent.parent / "synthetic_monitor.py"
_ALLOWLIST_PATH = Path(__file__).resolve().parent.parent / "_external_api_key_probe_allowlist.yaml"

# libs/ml-clients has its own config.py (shared across services, e.g.
# router_embedding_api_key) but is not under services/ — scanned explicitly,
# same as test_model_registry_completeness.py's _ML_CLIENTS_CONFIG handling.
_ML_CLIENTS_CONFIG = REPO_ROOT / "libs" / "ml-clients" / "src" / "ml_clients" / "config.py"

# A field name is treated as "a shared external API credential candidate"
# when it has "key" or "secret" as an underscore-delimited TOKEN (catches
# *_api_key, *_secret_key, *_access_key, *_consumer_key, *_client_secret,
# internal_jwt_private_key, brokerage_sync_jwt_secret, ...) or is a SnapTrade-
# style OAuth client id (ends in "_client_id"). Token-delimited (not a bare
# substring search) deliberately: "valkey_url" / "valkey_watchlist_key"'s
# "valkey" (the Redis fork this repo uses) contains the substring "key" — a
# bare `re.search(r"(key|secret)", ...)` would false-positive on every
# "valkey_*" field across nearly every service's config.py. Requiring an
# underscore (or start/end of string) on both sides of the token avoids that
# while still matching "valkey_watchlist_key"'s legitimate trailing "_key"
# suffix (that one IS a real, if non-credential, match — see the
# "Not-a-credential" allowlist category for why it's exempt, not why it's
# unmatched). Beyond that, this stays deliberately broad — false positives
# are cheap (one allowlist line each); false negatives are the actual danger
# this test exists to eliminate.
_KEY_CANDIDATE_NAME_RE = re.compile(r"(^|_)(key|secret)(_|$)", re.IGNORECASE)
_CLIENT_ID_SUFFIX_RE = re.compile(r"_client_id$", re.IGNORECASE)

# Longest-suffix-first so e.g. "eodhd_api_key" strips to "eodhd" (not
# "eodhd_api"), and "storage_secret_key" strips to "storage" (not
# "storage_secret").
_PROBE_NAME_SUFFIXES = (
    "_client_secret",
    "_consumer_key",
    "_access_key",
    "_secret_key",
    "_client_id",
    "_api_key",
    "_secret",
    "_key",
)


def _derive_probe_stem(field_name: str) -> str:
    """Strip the field's credential-shaped suffix to get the expected probe stem.

    E.g. ``"eodhd_api_key"`` -> ``"eodhd"`` -> expected function
    ``probe_eodhd_key`` in ``synthetic_monitor.PROBES``.
    """
    for suffix in _PROBE_NAME_SUFFIXES:
        if field_name.endswith(suffix):
            return field_name[: -len(suffix)]
    return field_name  # pragma: no cover — defensive; every candidate matches a suffix


@dataclass(frozen=True)
class SecretKeyField:
    service: str
    field: str
    file: str
    line: int


_STRING_LIKE_TYPE_NAMES = frozenset({"SecretStr", "str"})


def _annotation_is_string_like(annotation: ast.expr | None) -> bool:
    """True if the field's type annotation is (or includes) ``str``/``SecretStr``.

    Handles the bare form (``SecretStr`` / ``str``), the modern union form
    (``SecretStr | None`` / ``str | None`` — parsed as ``ast.BinOp`` with
    ``ast.BitOr``), and ``Optional[SecretStr]`` (``ast.Subscript``). Both
    ``str`` and ``SecretStr`` are included deliberately: several genuinely-
    shared external keys in this repo (``resend_api_key``, ``sendgrid_api_key``,
    ``content-ingestion.eodhd_api_key``, ``router_embedding_api_key``, …) are
    typed plain ``str``, not ``SecretStr`` — restricting to ``SecretStr``
    would silently miss exactly the fields this test exists to catch.
    """
    if annotation is None:
        return False
    for node in ast.walk(annotation):
        if isinstance(node, ast.Name) and node.id in _STRING_LIKE_TYPE_NAMES:
            return True
    return False


class _SecretKeyFieldVisitor(ast.NodeVisitor):
    """Collect str/SecretStr-typed, credential-shaped fields from *Settings classes."""

    def __init__(self) -> None:
        self.fields: list[tuple[str, int]] = []  # (field_name, line)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if "Settings" in node.name:
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    name = item.target.id
                    if not _annotation_is_string_like(item.annotation):
                        continue
                    if _KEY_CANDIDATE_NAME_RE.search(name) or _CLIENT_ID_SUFFIX_RE.search(name):
                        self.fields.append((name, item.lineno))
        self.generic_visit(node)


def _scan_config_for_secret_key_fields(config_py: Path, service: str) -> list[SecretKeyField]:
    if not config_py.exists():
        return []
    try:
        source = config_py.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        return []

    visitor = _SecretKeyFieldVisitor()
    visitor.visit(tree)

    rel = str(config_py.relative_to(REPO_ROOT))
    return [SecretKeyField(service=service, field=name, file=rel, line=line) for name, line in visitor.fields]


def _discover_all_secret_key_fields() -> list[SecretKeyField]:
    """Walk every service's (+ libs/ml-clients') config.py for credential-shaped fields."""
    found: list[SecretKeyField] = []
    if SERVICES_DIR.is_dir():
        for svc_dir in sorted(SERVICES_DIR.iterdir()):
            if not svc_dir.is_dir():
                continue
            src_dir = svc_dir / "src"
            if not src_dir.is_dir():
                continue
            # Find the single package dir under src/ (mirrors
            # tests/architecture/_utils.py's discover_services() convention).
            pkg_dirs = [p for p in src_dir.iterdir() if p.is_dir() and (p / "__init__.py").exists()]
            for pkg_dir in pkg_dirs:
                config_py = pkg_dir / "config.py"
                found.extend(_scan_config_for_secret_key_fields(config_py, svc_dir.name))
    found.extend(_scan_config_for_secret_key_fields(_ML_CLIENTS_CONFIG, "ml-clients"))
    return found


def _load_synthetic_monitor() -> ModuleType:
    """Import synthetic_monitor.py by file path (no package on sys.path) —
    same technique as test_synthetic_monitor.py, since infra/synthetic is a
    standalone script directory with no pyproject/__init__.py."""
    spec = importlib.util.spec_from_file_location("synthetic_monitor_registry_check", _MONITOR_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_allowlist() -> dict[tuple[str, str], dict[str, str]]:
    """Load the exemption allowlist, keyed by (service, field)."""
    if not _ALLOWLIST_PATH.exists():
        return {}
    raw = yaml.safe_load(_ALLOWLIST_PATH.read_text(encoding="utf-8")) or {}
    entries = raw.get("allowlist", [])
    keyed: dict[tuple[str, str], dict[str, str]] = {}
    for entry in entries:
        key = (entry["service"], entry["field"])
        keyed[key] = entry
    return keyed


class TestProbeRegistryCompleteness:
    def test_every_shared_api_key_is_probed_or_explicitly_exempted(self) -> None:
        """Every SecretStr credential-shaped config.py field must be accounted for.

        FAILS if a newly-configured shared/rotatable external API key ships
        with neither a matching ``probe_<name>_key`` in
        ``synthetic_monitor.PROBES`` nor a dated, justified exemption in
        ``infra/synthetic/_external_api_key_probe_allowlist.yaml`` — the exact
        gap that let probe_deepinfra_key / probe_eodhd_key only get built
        reactively, one incident at a time.
        """
        sm = _load_synthetic_monitor()
        probe_names = {fn.__name__ for fn in sm.PROBES}

        allowlist = _load_allowlist()
        fields = _discover_all_secret_key_fields()

        unaccounted = []
        for f in fields:
            expected_probe = f"probe_{_derive_probe_stem(f.field)}_key"
            if expected_probe in probe_names:
                continue
            if (f.service, f.field) in allowlist:
                continue
            unaccounted.append((f, expected_probe))

        assert not unaccounted, (
            "\nShared/rotatable external API key field(s) with NEITHER a matching "
            "freshness probe in infra/synthetic/synthetic_monitor.PROBES NOR an "
            "exemption in infra/synthetic/_external_api_key_probe_allowlist.yaml "
            "(would silently repeat the probe_deepinfra_key/probe_eodhd_key "
            "reactive-only-fix gap):\n"
            + "\n".join(
                f"  - {f.service}.{f.field}  ({f.file}:{f.line})  expected probe: {expected}"
                for f, expected in unaccounted
            )
            + (
                "\n\nFix: either add the probe function to PROBES, or add a dated, "
                "justified entry to infra/synthetic/_external_api_key_probe_allowlist.yaml."
            )
        )

    def test_allowlist_entries_still_resolve_to_real_config_fields(self) -> None:
        """Guard against a stale allowlist masking a field that was removed/renamed.

        Every (service, field) recorded in the allowlist must still be a real,
        currently-discovered SecretStr credential-shaped field — otherwise the
        allowlist could silently accumulate dead entries that no longer track
        anything (or, worse, a renamed field could slip back into the
        unaccounted set while an orphaned exemption for the OLD name remains).
        """
        allowlist = _load_allowlist()
        discovered_keys = {(f.service, f.field) for f in _discover_all_secret_key_fields()}

        stale_entries = [key for key in allowlist if key not in discovered_keys]

        assert not stale_entries, (
            "\nStale allowlist entries in infra/synthetic/_external_api_key_probe_allowlist.yaml "
            "no longer match any discovered SecretStr credential-shaped config.py field "
            "(field renamed/removed — update or delete the entry):\n"
            + "\n".join(f"  - {service}.{field}" for service, field in stale_entries)
        )

    def test_allowlist_schema_has_required_keys(self) -> None:
        """Every allowlist entry must carry the documented required fields."""
        if not _ALLOWLIST_PATH.exists():
            pytest.skip("allowlist file not present")
        raw = yaml.safe_load(_ALLOWLIST_PATH.read_text(encoding="utf-8")) or {}
        entries = raw.get("allowlist", [])
        assert entries, "allowlist file exists but has no entries — remove the file or add entries"
        required = {"service", "field", "file", "justification", "granted_at"}
        for entry in entries:
            missing = required - entry.keys()
            assert not missing, f"Allowlist entry {entry.get('service')}.{entry.get('field')} missing keys: {missing}"


class TestDeriveProbeStemUnit:
    """Isolated unit tests for ``_derive_probe_stem`` — pinned independently of
    whichever config.py fields happen to exist in the live repo today (Reviewer
    A flagged that suffix-stripping order/correctness was otherwise only ever
    exercised incidentally)."""

    def test_api_key_suffix(self) -> None:
        assert _derive_probe_stem("eodhd_api_key") == "eodhd"

    def test_secret_key_suffix_strips_to_shared_stem(self) -> None:
        # storage_access_key and storage_secret_key must derive the SAME stem
        # ("storage") so both map to one expected probe_storage_key name.
        assert _derive_probe_stem("storage_access_key") == "storage"
        assert _derive_probe_stem("storage_secret_key") == "storage"

    def test_client_id_suffix(self) -> None:
        assert _derive_probe_stem("snaptrade_client_id") == "snaptrade"

    def test_consumer_key_suffix(self) -> None:
        assert _derive_probe_stem("snaptrade_consumer_key") == "snaptrade"

    def test_bare_key_suffix_fallback(self) -> None:
        # No more specific suffix matches ("_jwt_secret" isn't in the list) —
        # falls through to the generic "_secret" suffix.
        assert _derive_probe_stem("brokerage_sync_jwt_secret") == "brokerage_sync_jwt"

    def test_longest_suffix_wins_not_shortest(self) -> None:
        # "_client_secret" must be tried before the generic "_secret", or
        # "oidc_client_secret" would incorrectly derive "oidc_client" instead
        # of "oidc".
        assert _derive_probe_stem("oidc_client_secret") == "oidc"


class TestSecretKeyFieldVisitorUnit:
    """Isolated unit test for the SecretStr/str credential-name scanner
    against a synthetic module — independent of live config.py contents.
    Also pins the "valkey" substring false-positive fix directly."""

    def test_visitor_matches_str_and_secretstr_credential_fields_only(self) -> None:
        source = """
class FooSettings:
    valkey_url: str = "redis://localhost:6379/0"
    valkey_watchlist_key: str = "svc:v1:watched"
    eodhd_api_key: str = ""
    deepinfra_api_key: SecretStr = SecretStr("")
    snaptrade_client_id: SecretStr = Field(default=SecretStr(""))
    log_level: str = "INFO"
"""
        tree = ast.parse(source)
        visitor = _SecretKeyFieldVisitor()
        visitor.visit(tree)
        names = {name for name, _line in visitor.fields}
        # valkey_url must NOT match (the "valkey" substring bug this test
        # guards against); valkey_watchlist_key DOES match (real "_key"
        # suffix — exempted via the allowlist's Not-a-credential category,
        # not by failing to match here).
        assert names == {
            "valkey_watchlist_key",
            "eodhd_api_key",
            "deepinfra_api_key",
            "snaptrade_client_id",
        }
