"""PromptTemplate — frozen, versioned, parameter-validated prompt container.

Version enhancement (2026-06-05):
- ``version`` is now semver-validated (``MAJOR.MINOR`` or ``MAJOR.MINOR.PATCH``)
  in ``__post_init__``. Non-conforming versions raise ``ValueError`` at import
  time, so a typo cannot slip into production.
- ``content_hash`` (12-char sha256 prefix of the template body) is computed
  once at construction. Lets callers persist a content-addressable identifier
  into evaluation artefacts so an old judge run is unambiguously linked to the
  rubric text that produced it — even if someone bumped ``version`` without
  changing the body, or vice versa.
- ``identifier()`` returns ``"name@version#hash"`` for log lines + artefact
  persistence (e.g. ``q_<id>.json["judge_prompt_id"]``).
"""

from __future__ import annotations

import hashlib
import re
import string
from dataclasses import dataclass, field

# Accept MAJOR.MINOR or MAJOR.MINOR.PATCH. Pre-release / build metadata is
# intentionally NOT supported — prompt evolution is linear and we never need
# to ship a "1.0-rc1". Keep it boring.
_SEMVER_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")


@dataclass(frozen=True, kw_only=True)
class PromptTemplate:
    """Typed prompt template with parameter validation + content addressing."""

    name: str
    version: str
    description: str
    template: str
    parameters: frozenset[str]
    # Computed in __post_init__; declared as field so dataclass picks it up but
    # callers should never pass it explicitly.
    content_hash: str = field(default="", init=False)

    def __post_init__(self) -> None:
        # Validate semver — fail loud at import time, not at LLM call time.
        if not _SEMVER_RE.match(self.version):
            msg = f"PromptTemplate {self.name!r}: version {self.version!r} is not semver (MAJOR.MINOR[.PATCH])"
            raise ValueError(msg)
        # Compute the 12-char sha256 prefix of the raw template body. This is
        # content-addressable: identical templates with different declared
        # versions still produce the same hash, and a single-char edit to the
        # template flips the hash even if version is unchanged. Persist it
        # alongside ``version`` in eval artefacts.
        digest = hashlib.sha256(self.template.encode("utf-8")).hexdigest()[:12]
        # frozen=True forbids normal attribute assignment; use object.__setattr__.
        object.__setattr__(self, "content_hash", digest)
        # --------------------------------------------------------------
        # Brace guard (MN-5, 2026-06-05).
        #
        # WHY: ``render()`` calls ``self.template.format_map(kwargs)`` which
        # treats ``{...}`` as a substitution slot. If a template author
        # embeds a literal JSON example (e.g. ``{"score": 25}``) without
        # doubling the braces, ``format_map`` will either raise a confusing
        # ``KeyError`` at first call OR — worse — silently substitute a
        # parameter that happens to share the name. We can't allow either.
        #
        # HOW: walk the template body with ``string.Formatter().parse``
        # which is the same parser ``str.format_map`` uses. For every
        # parsed slot we verify the field name is a declared parameter.
        # Literal braces MUST be escaped as ``{{`` / ``}}`` — the parser
        # handles that for us and yields them as plain literal text.
        # An unbalanced single brace makes ``parse`` raise ``ValueError``
        # which we re-raise with a clearer message.
        # --------------------------------------------------------------
        try:
            # ``parse`` returns tuples (literal_text, field_name, format_spec,
            # conversion). field_name is None for the trailing literal-only
            # chunk; anything else is a substitution slot we must validate.
            for _literal, field_name, _format_spec, _conversion in string.Formatter().parse(self.template):
                if field_name is None:
                    continue
                # Strip any indexing/attribute access — e.g. ``foo[0]`` or
                # ``foo.bar`` — and only validate the leading identifier
                # against the declared parameter set. Empty field names
                # (positional ``{}``) are not supported.
                root = re.split(r"[.\[]", field_name, maxsplit=1)[0]
                if not root:
                    msg = (
                        f"PromptTemplate {self.name!r}: positional placeholder '{{}}' is not allowed — "
                        f"use named placeholders (e.g. '{{claim}}') and declare them in parameters"
                    )
                    raise ValueError(msg)
                if root not in self.parameters:
                    msg = (
                        f"PromptTemplate {self.name!r}: template references undeclared placeholder "
                        f"{{{field_name}}} — either add {root!r} to parameters or escape literal "
                        f"braces as '{{{{' and '}}}}'"
                    )
                    raise ValueError(msg)
        except ValueError as exc:
            # ``string.Formatter().parse`` raises ValueError on a lone ``{`` or
            # ``}``. Wrap with a guidance message that points authors at the
            # escape form so a JSON example block can be added safely.
            # Re-raising our own messages above falls through here too — only
            # wrap the parser's native error.
            if str(exc).startswith(f"PromptTemplate {self.name!r}:"):
                raise
            msg = (
                f"PromptTemplate {self.name!r}: template contains unescaped brace — wrap literal "
                f"'{{' and '}}' as '{{{{' and '}}}}' or declare the slot as a parameter (parser said: {exc})"
            )
            raise ValueError(msg) from exc

    def render(self, **kwargs: str) -> str:
        """Substitute parameters into template.

        Raises ValueError if required parameters are missing.
        Extra kwargs beyond self.parameters are silently ignored.
        """
        missing = self.parameters - set(kwargs.keys())
        if missing:
            msg = f"Missing required parameters: {', '.join(sorted(missing))}"
            raise ValueError(msg)
        return self.template.format_map(kwargs)

    def identifier(self) -> str:
        """Return ``"name@version#hash"`` — stable, loggable, artefact-friendly.

        Used by:
        - Judge artefacts (``q_<id>.json["judge_prompt_id"]``) so a year-old
          run can be traced back to the exact rubric text that scored it.
        - structlog ``judge_prompt`` field for drift detection across rollouts.
        """
        return f"{self.name}@{self.version}#{self.content_hash}"
