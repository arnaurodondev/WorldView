# Bottleneck Audit — Content-Ingestion External-API Pagination/Backfill Correctness (2026-07-23)

**Author:** automated investigation (read-only source review, no live calls)
**Cluster:** content-ingestion external-API pagination/backfill correctness
**Scope:** verify the mined root-cause summary against current source under
`services/content-ingestion/src/content_ingestion/infrastructure/adapters/{polymarket,polymarket_gamma_events,polymarket_clob,polymarket_data_trades,polymarket_data_oi}/client.py`
and their test files, and produce a per-recurrence TEST_GAP / IMPLEMENTATION_GAP
classification with concrete remediation.

---

## TL;DR

- **The mined summary is confirmed against current source, verbatim.** Both Gamma
  clients (`polymarket/client.py`, `polymarket_gamma_events/client.py`) now correctly
  advance the cursor by the *actual* returned row count and terminate only on an
  empty page (fixed in `4b094c53e`, after `e1745828b` shipped the disproven "short
  page == done" heuristic one commit earlier). The sibling
  `polymarket_data_trades/client.py:94` still contains the **exact disproven
  heuristic** today: `has_more = len(trades) >= limit` — i.e. "fewer rows than
  requested == last page," the same assumption that broke Gamma twice.
- **`polymarket_clob/client.py` and `polymarket_data_oi/client.py` are single-shot
  (not paginated)** — out of scope for this specific bug class, but they share the
  same "no shared client base/helper" structural gap (see §3).
- **Classification: BOTH for the cluster as a whole**, but the two recurrences split
  cleanly:
  - Gamma /markets + /events (`e1745828b` → `4b094c53e`): **TEST_GAP**. The
    implementation approach (offset + "stop on short/empty page") was reasonable;
    what was missing was a test fixture encoding the *live* provider behavior
    (page capped below `limit`) before shipping. Once discovered, the fix commit
    **did** add exactly the missing regression tests (`test_short_page_still_advances`,
    `test_stop_on_empty_page` in `test_polymarket_client.py`) — good hardening, but
    reactive and per-client.
  - Trades client still using the disproven heuristic (present today, unfixed):
    **BOTH**. It is a test gap (no test exercises a short-but-nonempty page against
    the live-unverified Data-API contract) **and** a structural/implementation gap
    (there is no shared pagination primitive, so the Gamma fix never propagated
    here — a new engineer touching this file has no signal that the identical bug
    was already found and fixed twice in sibling files).
- **Severity/likelihood of recurrence: MEDIUM-HIGH.** The trades client bug is
  live and *may already be silently under-fetching trades* if the Polymarket
  Data-API caps page size below the requested `limit` the same way Gamma does
  (unverified as of this audit). Even if the Data-API contract happens to honor
  `limit` today, the absence of a shared helper means the **next** paginated
  Polymarket (or any other provider's) client is likely to reintroduce this exact
  bug a third time, because nothing in the codebase encodes the lesson as a reusable
  invariant — only as prose in two docstrings and two test files.

---

## 1. Recurrence-by-recurrence analysis

### 1a. Gamma `/markets` + `/events` — short page ≠ end of data (`e1745828b` → `4b094c53e`)

**What happened:** `e1745828b` introduced offset pagination for both Gamma clients
under the (docs-derived) assumption "a page is the last page when it returns fewer
than `limit` items." `4b094c53e`, filed ~11 minutes later the same night, found via
live smoke-testing that Gamma silently caps pages at ~100 rows regardless of the
requested `limit` (500), so the very first page is already "short" — the loop
terminated after ~100 markets/events instead of walking the full universe.

**Current source (verified):** Both `polymarket/client.py:157-166` and
`polymarket_gamma_events/client.py:160-169` now share (duplicated, not shared)
the corrected comment and logic:

```python
# Advance the synthetic cursor by the number of rows the API ACTUALLY
# returned, and stop only on an empty page. ...
next_offset: str | None = str(offset + len(markets)) if markets else None
```

**Tests added by the fix** (`tests/unit/infrastructure/adapters/test_polymarket_client.py`):
- `test_short_page_still_advances` — pins a 100-row page at `limit=500` and asserts
  `next_cursor` advances (does NOT stop).
- `test_stop_on_empty_page` — pins an empty page and asserts `next_cursor is None`.

These are exactly the regression tests that should have existed before `e1745828b`
shipped. `test_polymarket_events_adapter.py` was not fully inspected line-by-line
here, but the client-level fix and its two dedicated tests are present and correct.

**Classification: TEST_GAP.**
The chosen implementation (advance-by-actual-count, stop-on-empty) is the textbook
correct pattern for offset pagination against an unknown/variable page-size cap —
no further structural change is needed for these two files in isolation. What was
missing was a pre-ship test asserting the invariant "a short-but-nonempty page
must not terminate the walk," derived from the *provider's actual observed*
behavior rather than only from its documented behavior. That test now exists.

**Residual risk for these two files:** none material — the invariant is now
directly tested. Residual risk is entirely in the *propagation* gap (§1b, §3).

---

### 1b. `polymarket_data_trades/client.py` — same disproven heuristic, still live

**Current source (`client.py:37-103`), confirmed today:**

```python
@dataclass(frozen=True, slots=True)
class TradesPage:
    trades: list[dict]
    has_more: bool          # "True when a full page came back"
    ...
data = resp.json()
raw_trades = data.get("data", []) if isinstance(data, dict) else data
trades: list[dict] = [t for t in raw_trades if isinstance(t, dict)] if isinstance(raw_trades, list) else []
has_more = len(trades) >= limit
```

`has_more = len(trades) >= limit` is the same "full page vs short page" test that
was disproven for Gamma: any page shorter than the requested `limit` sets
`has_more = False`, and the adapter (`polymarket_data_trades/adapter.py:262`,
`:434`) stops on `not page.has_more`. If the Polymarket Data-API `/trades` endpoint
has (or ever adopts) the same silent page-size cap Gamma has, this client will
under-fetch trades for any market whose true trade count exceeds the cap — exactly
the ~101-row-universe bug, but for trade history instead of market listings.

**No docstring, commit message, or code comment anywhere in this file records a
live verification of the Data-API's actual page-size contract** — contrast this
with the Gamma clients, whose docstrings explicitly say "verified live 2026-07-16:
limit=500 → 100 rows." This absence is itself a signal: the Data-API contract was
never checked against live behavior, only assumed (mirroring the pre-fix Gamma
assumption).

**Tests inspected** (`tests/unit/infrastructure/adapters/test_polymarket_trades_adapter.py`
and `test_polymarket_trades_incremental.py`):
- `TestPolymarketTradesClient.test_wrapped_data_and_has_more` (line ~96) only
  checks the boundary case `len(trades) == limit` → `has_more True`; there is no
  test for "provider returns a short-but-nonempty page while more data actually
  exists" (the scenario that broke Gamma).
- All adapter-level tests (`test_offset_pagination_stops_at_max_pages`,
  `test_end_of_data_400_after_page_returns_collected`,
  `test_empty_page_breaks_pagination`, and the `*_incremental.py` suite) construct
  `TradesPage(...)` objects **directly with a hand-set `has_more` value**, bypassing
  the client's own `has_more` derivation entirely. They validate the adapter's
  loop-termination *given* a `has_more` flag, not whether the client computes that
  flag correctly against real provider behavior. This is precisely the same shape
  of test gap that existed pre-fix for Gamma: tests encode the *assumed* contract,
  not the *verified* one.

**Classification: BOTH.**
- **TEST_GAP** — no test exists (client-level or fixture-replay) asserting that a
  short-but-nonempty trades page still advances/continues, mirroring
  `test_short_page_still_advances` for Gamma. This is a direct, mechanical, and
  currently missing regression test.
- **IMPLEMENTATION_GAP** — even after adding that test and (presumably) flipping it
  to green by fixing the heuristic, there is still no structural mechanism
  preventing the *next* Polymarket (or other-provider) client from reintroducing
  this exact bug a third time, because pagination logic is hand-rolled per file
  with no shared primitive encoding "terminate only on empty page; advance by
  actual returned count." See §3 for the concrete fix.

---

## 2. What test(s) to add right now (mechanical, TEST_GAP portion)

File: `services/content-ingestion/tests/unit/infrastructure/adapters/test_polymarket_trades_adapter.py`
(client-level test class `TestPolymarketTradesClient`)

Add, mirroring `test_short_page_still_advances` in `test_polymarket_client.py`:

```python
async def test_short_page_treated_as_more_until_proven_otherwise(self) -> None:
    """A short-but-nonempty page must not silently end pagination.

    Regression for the disproven "len(trades) < limit == last page" heuristic
    that had to be fixed TWICE for the Gamma clients (e1745828b -> 4b094c53e)
    after the Gamma API turned out to silently cap page size below the
    requested `limit`. This client currently derives has_more the same
    (disproven) way -- has_more = len(trades) >= limit -- and the Data-API's
    real page-size contract has NOT been live-verified. This test pins the
    documented contract; if/when the Data-API is confirmed to cap pages below
    `limit`, this test (and the client) must be updated the same way the Gamma
    clients were.
    """
    # Provider returns fewer rows than requested (e.g. a silent page cap).
    client = _make_client(response_json={"data": [_raw_trade(f"0x{i}") for i in range(50)]})
    page = await client.fetch_trades_page(market="cond_1", limit=500)
    # Whatever the resolved policy, this MUST be an explicit, tested decision --
    # not an untested assumption. If the Data-API is confirmed NOT to cap pages
    # (unlike Gamma), assert has_more is False here and record the live
    # verification date/params in a code comment, exactly as the Gamma clients do.
    assert page.has_more is False  # TODO: replace with live-verified expectation
```

Additionally, add one adapter-level test using the **real client** (not a
hand-constructed `TradesPage`) so the has_more-derivation bug can't hide behind
mocks:

```python
async def test_adapter_does_not_stop_early_on_short_page_from_real_client(self) -> None:
    """End-to-end: drive the adapter against the real PolymarketTradesClient
    (httpx mocked at the transport layer, not TradesPage mocked directly) so a
    regression in has_more's derivation is caught at the adapter boundary too."""
    ...
```

Both tests should be added as part of the same change that resolves the
open question of whether the Data-API's page-size contract has been live-verified
(see recommendation below) — do not merely add the test and leave the `# TODO`.

---

## 3. Structural fix for the whole class of bug (IMPLEMENTATION_GAP portion)

Extract one shared, unit-tested pagination primitive used by every offset/cursor
paginated Polymarket client (and any future provider client), e.g.:

```python
# libs/... or services/content-ingestion/.../adapters/_pagination.py
def next_offset_cursor(
    *, offset: int, returned_count: int
) -> str | None:
    """Canonical offset-pagination termination rule for all providers in this
    client family.

    Terminates ONLY on an empty page (returned_count == 0). NEVER terminates on
    "returned_count < requested_limit" -- providers are free to silently cap
    page size below any requested limit (verified live for Polymarket Gamma
    2026-07-16: limit=500 -> 100 rows), and doing so is not a signal of
    end-of-data. Advances the offset by the ACTUAL returned row count, never by
    the requested limit, so no rows are skipped when the provider under-fills.
    """
    return str(offset + returned_count) if returned_count else None
```

Then:
1. Replace the duplicated inline logic in `polymarket/client.py` and
   `polymarket_gamma_events/client.py` with calls to this helper (behavior-
   preserving refactor — both already implement the correct rule, just
   independently).
2. Fix `polymarket_data_trades/client.py` to use the same helper instead of
   `has_more = len(trades) >= limit`, changing `TradesPage.has_more` to be derived
   from "was this page empty," not "was this page full."
3. Add a single shared test module (e.g. `test_pagination_helper.py`) that tests
   `next_offset_cursor` exhaustively (empty, short-nonempty, exactly-at-limit,
   over-limit-defensive) ONCE, instead of duplicating the same three test cases
   per client file.
4. Add a review-checklist line item (see `.claude/review/checklists/REVIEW_CHECKLIST.md`
   pagination entry, currently only "Query pagination has upper bound") requiring:
   *"New/modified offset or cursor pagination in an external-API adapter MUST use
   the shared `next_offset_cursor` helper (or equivalent) — inline
   `len(items) < limit` / `len(items) >= limit` termination checks are a known
   recurring bug class (Polymarket Gamma, `e1745828b`/`4b094c53e`) and must be
   flagged in review."*

This converts a "lesson learned twice in prose + duplicated tests" into a single
enforced invariant: the next engineer adding a 6th Polymarket client (or an EODHD
list endpoint) gets the correct behavior by construction, not by rediscovering it
via a production incident and a second live smoke-test.

---

## 4. Severity / likelihood assessment

| Recurrence | Status | Severity if it recurs/persists | Likelihood as-is |
|---|---|---|---|
| Gamma `/markets` + `/events` | Fixed + regression-tested | N/A (resolved) | Low — invariant is directly tested per-file |
| `polymarket_data_trades` `has_more` heuristic | **Unfixed, live today** | Medium-High — silent under-fetch of trade history if Data-API caps pages below `limit` (unverified); feeds prediction-market signal computation (PRD-0033), so under-fetched trades could silently bias OI/volume-derived scores | High for recurrence of the *class* elsewhere (no shared helper); unverified-but-plausible for *this instance already being active* today |
| Next new/modified paginated client (CLOB history windowing, OI, or a future EODHD list endpoint) | Not yet written / not yet regressed | Same as above | High, absent the shared helper — there is currently nothing in the codebase (helper, base class, or CI check) that would stop a 6th copy-pasted `len(items) < limit` heuristic from shipping |

**Top-priority action:** (1) live-verify the Polymarket Data-API `/trades`
page-size contract the same way Gamma was verified (a single read-only smoke
request with `limit` set higher than the market's known trade count), (2) fix
`polymarket_data_trades/client.py` to terminate only on an empty page regardless
of the outcome, and (3) extract the shared `next_offset_cursor` helper so this
cannot recur a third time in a sixth client.

---

## Appendix: files reviewed

- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/polymarket/client.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/polymarket_gamma_events/client.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/polymarket_clob/client.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/polymarket_data_oi/client.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/polymarket_data_trades/client.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/polymarket_data_trades/adapter.py`
- `services/content-ingestion/tests/unit/infrastructure/adapters/test_polymarket_client.py`
- `services/content-ingestion/tests/unit/infrastructure/adapters/test_polymarket_trades_adapter.py`
- `services/content-ingestion/tests/unit/infrastructure/adapters/test_polymarket_trades_incremental.py`
- commits `e1745828b`, `4b094c53e` (`git show --stat` + full messages)
