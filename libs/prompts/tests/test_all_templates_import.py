"""CI smoke test — every exported PromptTemplate imports cleanly and exposes a stable identifier.

WHY (DistSys F-007): with prompts now centralised, a future syntax error in
any one template module could brick every service that imports libs/prompts
at module load (rag-chat, nlp-pipeline, knowledge-graph). This test walks
the entire ``prompts.*`` package tree, finds every ``PromptTemplate``
instance, and asserts each one has:
  - a non-empty ``name``
  - a semver-valid ``version`` (enforced by ``__post_init__``)
  - a 12-char ``content_hash``
  - an ``identifier()`` that matches the canonical ``name@version#hash`` form

We also assert a sanity floor (≥10 templates discovered) so a silent module
load failure that returns 0 instances cannot make the test trivially pass.

Runs in <50ms; the fail-fast guard for libs/prompts as a whole.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import re

import prompts
import pytest
from prompts._base import PromptTemplate

# Canonical identifier shape — lowercase+underscore name, semver version
# (MAJOR.MINOR[.PATCH]), 12-char lowercase hex sha256 prefix.
_IDENTIFIER_RE = re.compile(r"^[a-z_]+@\d+\.\d+(\.\d+)?#[0-9a-f]{12}$")

# Minimum count: we know there are MANY more than 10 prompts in the lib
# today (briefing, chat, classification, description, evaluation, extraction,
# knowledge, retrieval). A floor of 10 guards against the failure mode
# where a templates module silently fails to import and getmembers() returns
# zero — pytest would otherwise show "0 collected" and exit green.
_MIN_TEMPLATE_COUNT = 10


def _discover_templates() -> list[tuple[str, PromptTemplate]]:
    """Walk ``prompts.*`` submodules and collect every PromptTemplate instance.

    Returns a list of ``(qualified_name, instance)`` tuples so a per-template
    failure shows the exact module-qualified path in the test ID, not just
    the bare ``name`` field (two prompts could share a name across modules
    in principle; the qualified path is unambiguous).
    """
    out: list[tuple[str, PromptTemplate]] = []
    # pkgutil.walk_packages walks the package tree; we feed it the
    # ``prompts`` package's __path__ and the ``"prompts."`` prefix so each
    # yielded ModuleInfo has the fully-qualified dotted name.
    for module_info in pkgutil.walk_packages(prompts.__path__, prefix="prompts."):
        # Skip private modules (``prompts._base``, ``prompts._safety``) —
        # they don't contain user-facing PromptTemplate instances.
        if any(part.startswith("_") for part in module_info.name.split(".")):
            continue
        # Import the module. We deliberately let any ImportError propagate —
        # a broken module IS the failure mode this smoke test is here to
        # detect.
        module = importlib.import_module(module_info.name)
        for attr_name, attr_value in inspect.getmembers(
            module,
            predicate=lambda x: isinstance(x, PromptTemplate),
        ):
            out.append((f"{module_info.name}.{attr_name}", attr_value))
    return out


# Discover once at module import time so the parametrize() decorator can use
# the list as test IDs. A discovery-time failure surfaces as a collection
# error, which is exactly what we want (fail-fast in CI).
_DISCOVERED = _discover_templates()


def test_discovered_at_least_minimum_count() -> None:
    """Sanity floor — at least _MIN_TEMPLATE_COUNT templates must be discovered.

    If a templates module fails to load silently, ``inspect.getmembers``
    returns nothing for that module and the per-template tests would not
    fire. This guard ensures pytest cannot exit green on a regression that
    breaks half the prompt library's imports.
    """
    assert len(_DISCOVERED) >= _MIN_TEMPLATE_COUNT, (
        f"Discovered only {len(_DISCOVERED)} PromptTemplate instances "
        f"(expected ≥ {_MIN_TEMPLATE_COUNT}). A templates module likely "
        f"failed to import. Discovered: {[name for name, _ in _DISCOVERED]}"
    )


@pytest.mark.parametrize(
    ("qualified_name", "template"),
    _DISCOVERED,
    ids=[name for name, _ in _DISCOVERED],
)
def test_template_has_stable_identifier(qualified_name: str, template: PromptTemplate) -> None:
    """Each discovered PromptTemplate must satisfy the identifier contract.

    Asserts (per template):
      - name is a non-empty string,
      - version is a non-empty string (semver is enforced by __post_init__,
        so we only need a truthiness check here),
      - content_hash is exactly 12 lowercase hex chars,
      - identifier() matches the canonical ``name@version#hash`` form.
    """
    assert template.name, f"{qualified_name}: empty name"
    assert template.version, f"{qualified_name}: empty version"
    assert len(template.content_hash) == 12, f"{qualified_name}: content_hash {template.content_hash!r} is not 12 chars"
    # Hash must be lowercase hex — sha256().hexdigest() returns lowercase
    # but a future refactor could break that invariant.
    assert re.match(
        r"^[0-9a-f]{12}$", template.content_hash
    ), f"{qualified_name}: content_hash {template.content_hash!r} is not 12-char lowercase hex"
    ident = template.identifier()
    assert _IDENTIFIER_RE.match(
        ident
    ), f"{qualified_name}: identifier {ident!r} does not match {_IDENTIFIER_RE.pattern!r}"
