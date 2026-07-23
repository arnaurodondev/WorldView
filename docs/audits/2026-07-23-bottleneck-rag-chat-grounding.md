# rag-chat Grounding/Citation Whack-a-Mole — Recurrence Classification & Structural Fix

**Date:** 2026-07-23
**Scope:** READ-ONLY source investigation of `services/rag-chat` (prompt, tool_use, citation
resolution, grounding gate) and its `tests/` directory, plus the referenced commit history.
Deliberately narrow write scope per task instructions — this file only.
**Author:** automated audit (Claude)

---

## TL;DR

The mined cluster is real and correctly diagnosed as a code-shape smell (heuristic accretion
in a 7,408-line `chat_orchestrator.py` and a 2,794-line `numeric_grounding.py`, plus a
1,448-line additive prompt). **But the "already_in_bug_patterns / already_in_high_risk_patterns
/ already_in_review_checklist: No" claims in the mined summary are stale.** As of this working
tree, `docs/BUG_PATTERNS.md` (BP-734, BP-735), `.claude/review/heuristics/HIGH_RISK_PATTERNS.md`
(HR-065 and a paired prompt-directive entry), and `.claude/review/checklists/REVIEW_CHECKLIST.md`
(line 117) **already contain** entries that are near-verbatim matches to the cluster's
"suggested" text — almost certainly written by a prior `/docs-audit` pass in this same
worktree. **These are uncommitted working-tree modifications** (`git status` shows all three
files as `M`, not yet committed; `git log -S` finds no commit introducing BP-734/BP-735/HR-065).
The immediate, zero-risk action is to **commit those three diffs** — the documentation half of
this bottleneck is already solved and sitting on disk.

What remains genuinely open, and is the substance of this report, is the two recurrence
classes' TEST_GAP vs. IMPLEMENTATION_GAP split and whether the existing (uncommitted) checklist
item is sufficient to prevent recurrence, which it is **not** by itself — it only makes the
regression *reviewable*, it does not make it *checkable* by CI.

---

## 1. Recurrence classification

### Recurrence A — Citation-tag heuristic accretion (`af69dbbaa`, `fe1d32ad2`, `3934d26eb`,
`45b658695`, `36a9df0e0`) in `numeric_grounding.py` / `chat_orchestrator.py`

**Classification: BOTH (TEST_GAP dominant).**

Reading the actual code (`resolve_tool_name`, `partition_phantom_tool_citations`,
`normalize_tool_row_citations`, `_strip_non_registered_citation_tags`) confirms each fix is
disciplined and well-commented — every new normalizer is explicitly gated so a genuinely
never-run tool still resolves to `None`/phantom (e.g. `resolve_tool_name`'s difflib step only
fires above a `0.85` ratio; the fundamentals-family alias in `partition_phantom_tool_citations`
requires the family tool to have *actually run* and the cited value to be *present in its
returned pool* before treating a mismatched name as grounded). This is not sloppy code — each
individual fix is narrowly scoped and tested (186 new tests in `af69dbbaa` alone,
`test_numeric_grounding.py` at 1,063 lines, `test_phantom_citation_partition.py` dedicated to
this exact function).

The gap is **structural, not test-quality**: there is no test that asserts the *conjunction* of
all five normalizers together still preserves the phantom-refusal invariant on a case that
combines two variant classes at once (e.g. a difflib-typo'd tool name for a tool that *also*
happens to be in `_FUNDAMENTALS_FAMILY_TOOLS`, or a namespace-prefixed name plus an
out-of-range row index, resolved in the same string). Each PR's test suite pins the **new**
guard against the **specific case that motivated it**, exactly as the mined summary states, but
none of the five test files exercise two normalizers on the same tag simultaneously. This is a
TEST_GAP in the narrow sense (a combinatorial test file does not exist) that is masking (and
will keep masking) an IMPLEMENTATION_GAP: `resolve_tool_name`, `partition_phantom_tool_citations`,
and `_strip_non_registered_citation_tags` are three separate call sites that each re-derive
"is this citation real" with slightly different logic and ordering (confirmed by reading
`partition_phantom_tool_citations`'s docstring, which explicitly says
`find_phantom_tool_citations` is "intentionally left UNCHANGED" as a stricter sibling — i.e.
there are *two* phantom-detection functions in the same file with different strictness, used by
different callers). A single shared `CitationResolver.classify(tag) -> {REAL, PHANTOM_MATERIAL,
PHANTOM_BENIGN}` with one ordered pipeline would make "does normalizer N interact with
normalizer M" a property of one function's unit tests instead of an emergent property of two
call sites' interaction — this is what HR-065 (already drafted, uncommitted) correctly
recommends.

**What test(s) should be added** (concrete, actionable regardless of the refactor):
- New file `services/rag-chat/tests/unit/application/services/test_citation_normalizer_interactions.py`
  with a parametrized matrix crossing at least: {exact name, dropped-prefix, namespace-prefixed,
  difflib-typo, fundamentals-family-alias} × {in-range row, out-of-range row, never-called tool}
  × {material number adjacent, benign prose only}. Each cell asserts the SAME final
  classification (real/strip/refuse) regardless of which normalizer function is invoked first —
  i.e. a property test for order-independence of `resolve_tool_name` →
  `normalize_tool_row_citations` → `partition_phantom_tool_citations` when chained, not just each
  tested standalone.
- A regression case with a difflib-typo'd name (`fundamentls_history` — two mutations away) that
  ALSO belongs to `_FUNDAMENTALS_FAMILY_TOOLS`, asserting the family-alias gate is not
  short-circuited by the typo resolver returning a wrong canonical name first.

### Recurrence B — Prompt-directive interaction regression (`39daa5013` → `24f71c0d2`)

**Classification: IMPLEMENTATION_GAP (this one genuinely cannot be closed by more unit tests).**

Confirmed by reading both diffs directly: v1.23 added a "BATCH WIDTH" directive with broad,
unscoped imperative language ("a multi-faceted question... needs 4-6 independent tools", "when
in doubt... INCLUDE it"). The regression it caused — `cmp_nvda_amd` dropping `traverse_graph`,
the one tool the question named explicitly — was found by a live A/B run against Qwen3-235B
("latency-investigator" in the commit message), **not** by `libs/prompts/tests/test_tool_use_prompt.py`
(1,071 lines of tests, which only assert the prompt's *static string contract* — version bump,
presence of the new clause text, absence of removed clauses). No unit test of a prompt string
can predict how an LLM will weigh two competing imperative clauses against each other; that is
an empirical fact about the artifact (a natural-language prompt interpreted by a stochastic
model), not a test-authoring gap. Writing "more tests" in the traditional sense does not fix
this — the fix has to be procedural/infrastructural:

**Concrete structural fix** (already correctly identified by the uncommitted checklist item at
`REVIEW_CHECKLIST.md:117`, but that item alone is insufficient — it depends on a human reviewer
remembering to ask for evidence of an A/B run, with no gate that blocks the merge if absent):
1. **CI-enforced live-eval gate**, not just a checklist reminder: any diff that changes
   `TOOL_USE_SYSTEM_PROMPT_TEMPLATE.version` in `libs/prompts/src/prompts/chat/tool_use.py`
   should require (via a pre-PR hook, mirroring the existing "Pre-PR checklist" hook pattern
   already in `CLAUDE.md`) a machine-readable artifact — e.g. a JSON result file from the
   existing chat-quality eval harness — proving a live run was executed against the FULL
   regression question set (not a subset chosen by the author) and that no previously-passing
   question dropped a previously-called tool. Absent that artifact, the pre-PR hook should fail
   the same way the ruff/mypy pre-commit hook already fails builds.
2. **A held-out "unrelated question shape" battery** specifically for tool-selection stability:
   maintain a small fixed set of questions (e.g. `cmp_nvda_amd`, `agg_q5_tsla_macro`) each
   annotated with the SPECIFIC tool(s) they must call, independent of the eval's pass/fail
   judge score — this is a narrower, cheaper, deterministic-enough signal ("did tool X appear in
   the call trace, yes/no") than the full LLM-judged quality eval, and could plausibly run in CI
   against a cheaper/faster model as a smoke check even though it can't fully replace the
   Qwen3-235B live A/B.
3. Both are process/tooling additions, not code inside `chat_orchestrator.py` — there is no
   "circuit breaker abstraction" that prevents a prompt clause from changing model behavior; the
   only lever is pre-merge live verification, made mandatory rather than optional.

---

## 2. Are the already-drafted (uncommitted) doc entries sufficient?

Reading the actual diffs (`git diff docs/BUG_PATTERNS.md .claude/review/heuristics/HIGH_RISK_PATTERNS.md
.claude/review/checklists/REVIEW_CHECKLIST.md`) confirms:
- BP-734 and BP-735 correctly name both recurrence classes and their root causes, matching the
  investigation above.
- HR-065 correctly flags "new regex/string matcher added to citation/grounding files without
  checking for an existing normalizer" as a review-time signal, and separately flags broad
  imperative prompt directives without an accompanying live-eval artifact.
- REVIEW_CHECKLIST.md:117 requires "validated via a live A/B run... not just unit tests" for any
  `tool_use.py` version bump.

These are good and should be committed as-is. **They are necessary but not sufficient**: HR-065
and the checklist item are advisory text a reviewer reads; nothing in the repo's hook
infrastructure (`scripts/hooks/`) currently enforces either the "does this duplicate an existing
normalizer" question or the "was a live A/B artifact attached" requirement mechanically. Until
one of the two structural fixes in §1 (a `CitationResolver` module refactor; a CI-checked
live-eval artifact requirement) exists, the documentation closes the *review-signal* gap but not
the *recurrence* gap — a reviewer under time pressure can still wave through PR #7's "one more
regex" the same way #1 through #6 were waved through, because nothing blocks the merge.

---

## 3. Severity / likelihood assessment

| Recurrence | Severity if it recurs | Likelihood as-is | Likelihood after committing the 3 doc diffs only | Likelihood after the structural fixes in §1 |
|---|---|---|---|---|
| A — citation heuristic accretion | Medium (false-refuse or false-cite; user-visible answer quality, not data corruption — grounding gate fails safe on the strict side per the phantom-refusal invariant) | High — new LLM phrasing variants are a certainty, not a maybe | Medium-High — reviewer now has a naming/signal but no gate | Low-Medium — combinatorial tests + eventual `CitationResolver` consolidation catch most, but "an LLM writes something new" remains open-ended |
| B — prompt-directive interaction | Medium-High (silently drops a named, user-critical tool call — a comparison question silently loses its most specific evidence source) | High — `tool_use.py` will keep growing; this is the SECOND such regression (`1e8744443` "reverse v1.17 hypo regression" is a prior instance of the same class) | Medium — checklist item exists but is not CI-gated, so compliance depends on discipline under time pressure | Low — a CI-blocking gate requiring an attached live-eval artifact removes the "forgot to A/B test" failure mode entirely; residual risk is only "the battery didn't include the shape that regresses" |

**Bottom line:** the mined bottleneck hypothesis is directionally correct and, per the historical
`1e8744443` precedent, this is not the first recurrence of class B — it is at least the second.
The single highest-leverage next action is not writing new doc prose (already done, uncommitted)
but making the live-eval-artifact requirement a **CI gate** rather than a checklist line, since
that is the only lever that has ever actually stopped this class of bug (the A/B run in
`24f71c0d2` itself), and it currently depends entirely on the author remembering to run it.

---

## 4. Recommended next actions (in order)

1. **Commit the three uncommitted doc diffs** (`docs/BUG_PATTERNS.md`, `HIGH_RISK_PATTERNS.md`,
   `REVIEW_CHECKLIST.md`) — zero-risk, already-written, currently sitting unlanded in the
   working tree.
2. Add `services/rag-chat/tests/unit/application/services/test_citation_normalizer_interactions.py`
   per §1-Recurrence-A's matrix — closes the immediate TEST_GAP cheaply.
3. Convert the `REVIEW_CHECKLIST.md:117` advisory item into a CI-enforced pre-PR hook check
   (extending the existing "Pre-PR checklist" hook already documented in `CLAUDE.md`) that fails
   a PR touching `tool_use.py`'s version constant unless a live-eval artifact is attached —
   closes the IMPLEMENTATION_GAP for recurrence class B.
4. Longer-term (not blocking): extract `CitationResolver`/`GroundingValidator` per HR-065 out of
   `chat_orchestrator.py`/`numeric_grounding.py` so future citation-format variants are added in
   one place with one ordering contract instead of a sixth parallel special case.
