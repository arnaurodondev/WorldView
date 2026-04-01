"""
Architecture test: Docker Compose ↔ entry point alignment (T-A-3-01).

Verifies that:
1. Every ``*_main.py`` entry point in a mature service has a corresponding
   Docker Compose container in ``infra/compose/docker-compose.test.yml``.
2. Every ``python -m <module>`` command in the compose file resolves to an
   existing ``.py`` file in the matching service's ``src/`` directory.
3. No orphaned containers — compose commands reference modules that still exist.

Per STANDARDS.md §14.3, RULES.md R22.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import yaml

from tests.architecture._utils import (
    REPO_ROOT,
    discover_mature_services,
    discover_process_entry_points,
    discover_services,
    module_path_from_file,
)

COMPOSE_TEST_FILE = REPO_ROOT / "infra" / "compose" / "docker-compose.test.yml"

# ---------------------------------------------------------------------------
# Baseline — known entry points without compose containers (awaiting migration)
# ---------------------------------------------------------------------------
# Key: (service_name, main_file_stem) → reason / planned fix wave.
#
# Add an entry here when a *_main.py exists but its compose container has not
# yet been added.  Remove it once the container is wired up.
COMPOSE_BASELINE: dict[tuple[str, str], str] = {
    # All known gaps resolved in PLAN-0011 follow-up (docker-compose additions).
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_compose_module_commands(compose_file: Path) -> list[tuple[str, str]]:
    """Parse docker-compose YAML and return ``[(compose_service, module_path), ...]``.

    Filters to services whose ``command`` is ``["python", "-m", "<module>"]``
    (or ``python3``).  Infrastructure-only services (postgres, kafka, etc.) are
    excluded because they do not use Python module entry points.
    """
    with compose_file.open() as fh:
        data: dict[str, Any] = yaml.safe_load(fh)

    results = []
    for svc_name, svc_cfg in data.get("services", {}).items():
        if not isinstance(svc_cfg, dict):
            continue
        cmd = svc_cfg.get("command")
        if not isinstance(cmd, list) or len(cmd) < 3:
            continue
        if cmd[0] in ("python", "python3") and cmd[1] == "-m":
            results.append((svc_name, cmd[2]))
    return results


def _module_to_file(module_path: str, src_dirs: dict[str, Path]) -> Path | None:
    """Convert a dotted module path to an absolute ``.py`` file path.

    Uses the first component of the module path as the package name to look up
    the service's ``src/`` directory.  Returns ``None`` if the package is not
    found in the services list.
    """
    pkg_name = module_path.split(".")[0]
    src_dir = src_dirs.get(pkg_name)
    if src_dir is None:
        return None
    rel_path = module_path.replace(".", "/") + ".py"
    return src_dir / rel_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestComposeAlignment:
    def test_compose_commands_resolve_to_files(self) -> None:
        """Every ``python -m <module>`` in docker-compose.test.yml resolves to an existing .py file."""
        src_dirs = {svc.pkg_name: svc.src_dir for svc in discover_services()}
        violations = []

        for compose_svc, module_path in _parse_compose_module_commands(COMPOSE_TEST_FILE):
            py_file = _module_to_file(module_path, src_dirs)
            if py_file is None:
                violations.append(
                    f"  compose-service '{compose_svc}': module '{module_path}' "
                    f"— package not found in any service src/ dir"
                )
            elif not py_file.exists():
                violations.append(
                    f"  compose-service '{compose_svc}': module '{module_path}' "
                    f"→ {py_file.relative_to(REPO_ROOT)} does not exist"
                )

        assert not violations, (
            f"\n[COMPOSE-RESOLVE] {len(violations)} compose module path(s) do not resolve to files:\n"
            + "\n".join(violations)
        )

    def test_no_stale_compose_module_paths(self) -> None:
        """No docker-compose.test.yml command references a non-existent Python module.

        This catches stale paths left behind after file renames (e.g. a compose
        container still pointing at ``schedulers.scheduler`` after the directory
        was renamed to ``scheduler/``).
        """
        src_dirs = {svc.pkg_name: svc.src_dir for svc in discover_services()}
        stale = []

        for compose_svc, module_path in _parse_compose_module_commands(COMPOSE_TEST_FILE):
            py_file = _module_to_file(module_path, src_dirs)
            if py_file is not None and not py_file.exists():
                stale.append(f"  {compose_svc}: '{module_path}' → {py_file.relative_to(REPO_ROOT)}")

        assert not stale, (
            "\n[COMPOSE-STALE] Stale module path(s) in docker-compose.test.yml "
            "(file no longer exists — update the compose command):\n" + "\n".join(stale)
        )

    def test_every_entry_point_has_compose_container(self) -> None:
        """Each ``*_main.py`` in mature services should have a container in docker-compose.test.yml.

        Uses COMPOSE_BASELINE to allow known gaps.  Baseline violations are
        printed as warnings.  Stale baseline entries (the file was removed or
        the container was added) emit a UserWarning so they can be cleaned up.
        """
        # Build the set of module paths covered by compose containers.
        compose_modules: set[str] = {
            module_path for _, module_path in _parse_compose_module_commands(COMPOSE_TEST_FILE)
        }

        violations = []
        warned: set[tuple[str, str]] = set()

        for svc in discover_mature_services():
            for ep in discover_process_entry_points(svc):
                if ep.main_file is None:
                    continue  # missing *_main.py is caught by test_process_topology.py
                expected_module = module_path_from_file(ep.main_file, svc.src_dir)
                key = (svc.name, ep.main_file.stem)

                if expected_module not in compose_modules:
                    if key in COMPOSE_BASELINE:
                        if key not in warned:
                            warnings.warn(
                                f"[COMPOSE-MAIN-MISSING baseline] {svc.name}: "
                                f"{ep.main_file.name} has no compose container. "
                                f"Reason: {COMPOSE_BASELINE[key]}",
                                stacklevel=2,
                            )
                            warned.add(key)
                    else:
                        violations.append(
                            f"  {svc.name}: {ep.main_file.name} "
                            f"(expected module: {expected_module}) "
                            f"has no matching container in docker-compose.test.yml"
                        )

        # Check for stale baseline entries (file removed or container added).
        all_ep_keys: set[tuple[str, str]] = set()
        for svc in discover_mature_services():
            for ep in discover_process_entry_points(svc):
                if ep.main_file is not None:
                    all_ep_keys.add((svc.name, ep.main_file.stem))

        for key, reason in COMPOSE_BASELINE.items():
            if key not in all_ep_keys:
                warnings.warn(
                    f"[COMPOSE-BASELINE stale] {key} is in COMPOSE_BASELINE but has no "
                    f"matching entry point file. Remove it. Reason was: {reason}",
                    stacklevel=2,
                )

        assert not violations, (
            f"\n[COMPOSE-MAIN-MISSING] {len(violations)} entry point(s) lack compose containers:\n"
            + "\n".join(violations)
            + "\nAdd a container or add to COMPOSE_BASELINE with a fix wave."
        )
