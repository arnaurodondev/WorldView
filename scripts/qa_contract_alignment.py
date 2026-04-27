# ruff: noqa: S310
#!/usr/bin/env python3
"""Contract alignment checker — verifies frontend mock fixtures match real S9 API response shapes.

Detects "mock drift" by comparing the TypeScript mock fixtures in api-mocks.ts
against live S9 API responses. Reports missing keys, extra keys, type mismatches,
and potential key renames.

Usage (S9 must be running on localhost:8000):
    python scripts/qa_contract_alignment.py

Exit codes:
    0 = all checked endpoints match
    1 = at least one mismatch found
    2 = script error (file not found, parse failure, etc.)
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any

# ── Configuration ────────────────────────────────────────────────────────────

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOCK_FILE = os.path.join(
    REPO_ROOT,
    "apps",
    "worldview-web",
    "e2e",
    "fixtures",
    "api-mocks.ts",
)

S9_BASE = os.environ.get("S9_BASE_URL", "http://localhost:8000")
DEV_LOGIN_URL = f"{S9_BASE}/v1/auth/dev-login"

# Map of mock constant name -> (HTTP method, real S9 path, optional request body for POST)
# Only endpoints that have meaningful response shapes (not empty arrays or wildcard catch-alls).
ENDPOINT_MAP: list[tuple[str, str, str, dict[str, Any] | None]] = [
    ("PORTFOLIOS_RESPONSE", "GET", "/v1/portfolios", None),
    ("WATCHLISTS_RESPONSE", "GET", "/v1/watchlists", None),
    ("NEWS_TOP_RESPONSE", "GET", "/v1/news/top", None),
    ("NEWS_RELEVANT_RESPONSE", "GET", "/v1/news/relevant", None),
    ("MARKET_HEATMAP_RESPONSE", "GET", "/v1/market/heatmap", None),
    ("TOP_MOVERS_RESPONSE", "GET", "/v1/market/top-movers?type=gainers&limit=5", None),
    ("ALERTS_PENDING_RESPONSE", "GET", "/v1/alerts/pending", None),
    ("MORNING_BRIEF_RESPONSE", "GET", "/v1/briefings/morning", None),
    ("AI_SIGNALS_RESPONSE", "GET", "/v1/signals/ai", None),
    ("PREDICTION_MARKETS_RESPONSE", "GET", "/v1/signals/prediction-markets", None),
    ("ECONOMIC_CALENDAR_RESPONSE", "GET", "/v1/fundamentals/economic-calendar", None),
    ("SEARCH_RESPONSE", "GET", "/v1/search/instruments?query=test", None),
    ("BATCH_QUOTES_RESPONSE", "POST", "/v1/quotes/batch", {"instrument_ids": []}),
    ("HOLDINGS_RESPONSE", "GET", "/v1/holdings/placeholder", None),
    ("TRANSACTIONS_RESPONSE", "GET", "/v1/transactions", None),
    ("THREADS_RESPONSE", "GET", "/v1/threads", None),
    ("SCREENER_FIELDS_RESPONSE", "GET", "/v1/fundamentals/screen/fields", None),
]

# Inline mock shapes defined directly in getStrictEndpointMocks (not as named constants).
# These are extracted manually since they aren't top-level const exports.
INLINE_MOCKS: dict[str, tuple[str, str, dict[str, Any]]] = {
    "fundamentals/screen": (
        "POST",
        "/v1/fundamentals/screen",
        {"results": [], "total": 0},
    ),
    "quotes/single": (
        "GET",
        "/v1/quotes/placeholder",
        {
            "instrument_id": "ins-001",
            "ticker": "AAPL",
            "price": 0,
            "change": 0,
            "change_pct": 0,
            "timestamp": "2026-04-18T00:00:00Z",
            "volume": 0,
        },
    ),
    "ohlcv": (
        "GET",
        "/v1/ohlcv/placeholder",
        {"instrument_id": "ins-001", "ticker": "", "timeframe": "1D", "bars": []},
    ),
    "entity_graph": (
        "GET",
        "/v1/entities/placeholder/graph",
        {"entity_id": "ent-001", "nodes": [], "edges": []},
    ),
    "entity_contradictions": (
        "GET",
        "/v1/entities/placeholder/contradictions",
        {"entity_id": "ent-001", "contradictions": []},
    ),
    "thread_detail": (
        "GET",
        "/v1/threads/placeholder",
        {"thread_id": "t-1", "title": "", "messages": []},
    ),
    "company_overview": (
        "GET",
        "/v1/companies/placeholder/overview",
        {
            "instrument_id": "ins-001",
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "fundamentals": None,
            "recent_bars": [],
            "recent_news": [],
        },
    ),
}


# ── Shape extraction utilities ───────────────────────────────────────────────


def typeof(value: Any) -> str:
    """Return a canonical type name for a JSON value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "number"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def extract_shape(value: Any) -> dict[str, Any] | str:
    """Recursively extract the type shape of a JSON value.

    Returns a dict mapping keys to their types/shapes for objects,
    or a type string for scalars/arrays.
    """
    if isinstance(value, dict):
        shape: dict[str, Any] = {}
        for k, v in value.items():
            shape[k] = extract_shape(v)
        return shape
    if isinstance(value, list):
        if len(value) > 0:
            return {"__array_element__": extract_shape(value[0])}
        return {"__array_element__": "unknown"}
    return typeof(value)


def flatten_shape(shape: dict[str, Any] | str, prefix: str = "") -> dict[str, str]:
    """Flatten a nested shape dict into dot-separated paths with type strings.

    Example: {"items": {"__array_element__": {"id": "string"}}}
    becomes: {"items": "array", "items[].id": "string"}
    """
    result: dict[str, str] = {}
    if isinstance(shape, str):
        result[prefix] = shape
        return result
    if isinstance(shape, dict):
        for k, v in shape.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if k == "__array_element__":
                # The parent is an array — record element shape
                if isinstance(v, dict):
                    child_flat = flatten_shape(v, f"{prefix}[]")
                    result.update(child_flat)
                else:
                    result[f"{prefix}[]"] = v
            elif isinstance(v, dict):
                if "__array_element__" in v:
                    # This key holds an array
                    result[full_key] = "array"
                    elem = v["__array_element__"]
                    if isinstance(elem, dict):
                        child_flat = flatten_shape(elem, f"{full_key}[]")
                        result.update(child_flat)
                    else:
                        result[f"{full_key}[]"] = elem
                else:
                    # Nested object
                    result[full_key] = "object"
                    child_flat = flatten_shape(v, full_key)
                    result.update(child_flat)
            else:
                result[full_key] = v
    return result


# ── Mock file parser ─────────────────────────────────────────────────────────


def _strip_ts_types(text: str) -> str:
    """Remove TypeScript type annotations from object literals so they parse as JSON.

    Handles patterns like:
        [] as unknown[]
        [] as Array<{ entity_id: string; name: string; ticker: string | null }>
        null as Foo | null

    Strategy: find each " as " and consume everything until we hit a character
    that cannot be part of a TS type annotation AND is not inside angle brackets
    or braces. Concretely, we track <> nesting and {} nesting within the type
    expression, stopping when depth==0 and we see a comma, closing bracket/brace,
    or semicolon that belongs to the outer JSON structure.
    """
    result: list[str] = []
    i = 0
    while i < len(text):
        # Look for " as " keyword (preceded by whitespace or end-of-value chars)
        if text[i : i + 4] == " as " and i > 0 and text[i - 1] in "])}\"'0nNrue":
            # Skip " as " and then consume the type expression
            j = i + 4
            depth = 0  # track <> and {} nesting
            while j < len(text):
                ch = text[j]
                if ch in "<{":
                    depth += 1
                elif ch in ">}":
                    if depth > 0:
                        depth -= 1
                    else:
                        break
                elif depth == 0 and ch in ",;\n":
                    break
                j += 1
            i = j  # skip past the type annotation
        else:
            result.append(text[i])
            i += 1
    return "".join(result)


def _ts_object_to_json(text: str) -> str:
    """Convert a TypeScript object literal to valid JSON.

    Handles:
    - Unquoted keys
    - Trailing commas
    - Single-line comments
    - Function calls like buildFakeToken() -> placeholder string
    """
    # Replace function calls with placeholder strings
    text = re.sub(r"buildFakeToken\([^)]*\)", '"__function_call__"', text)

    # Remove single-line comments
    text = re.sub(r"//[^\n]*", "", text)

    # Quote unquoted object keys: word_chars followed by colon
    # But don't re-quote already-quoted keys
    text = re.sub(r"(?<=[{,\n])\s*(\w+)\s*:", r' "\1":', text)

    # Remove trailing commas before } or ]
    text = re.sub(r",\s*([}\]])", r"\1", text)

    return text


def parse_mock_constants(source: str) -> dict[str, Any]:
    """Extract named const mock objects from api-mocks.ts source code.

    Returns a dict of constant_name -> parsed JSON value.
    """
    results: dict[str, Any] = {}

    # Match patterns like: export const FOO_RESPONSE = { ... };
    # or: export const FOO_RESPONSE: Type = { ... };
    # or: export const FOO_RESPONSE: Type[] = [];
    pattern = re.compile(
        r"export\s+const\s+(\w+_RESPONSE)\s*(?::\s*[^=]+)?\s*=\s*" r"([\s\S]*?);\s*\n",
        re.MULTILINE,
    )

    for match in pattern.finditer(source):
        name = match.group(1)
        raw_value = match.group(2).strip()

        # Strip TS type annotations
        cleaned = _strip_ts_types(raw_value)
        # Convert to JSON
        json_str = _ts_object_to_json(cleaned)

        try:
            parsed = json.loads(json_str)
            results[name] = parsed
        except json.JSONDecodeError as e:
            print(f"  WARNING: Could not parse mock constant '{name}': {e}")
            print(f"    Raw: {raw_value[:120]}...")
            print(f"    Cleaned JSON: {json_str[:120]}...")

    return results


# ── S9 API client ────────────────────────────────────────────────────────────


def get_dev_token() -> str | None:
    """Obtain a dev-login JWT from S9. Returns None if S9 is unreachable."""
    payload = json.dumps({"email": "qa-contract@test.local", "name": "QA Contract"}).encode()
    req = urllib.request.Request(
        DEV_LOGIN_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("access_token") or data.get("token")
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        print(f"WARNING: Could not obtain dev-login token: {e}")
        return None


def call_endpoint(
    method: str,
    path: str,
    token: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    """Call an S9 endpoint. Returns (status_code, parsed_json_or_None)."""
    url = f"{S9_BASE}{path}"
    data = json.dumps(body).encode() if body else None
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode()
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, None
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, OSError):
        return -1, None


# ── Shape comparison ─────────────────────────────────────────────────────────


class Mismatch:
    """A single shape mismatch between mock and real response."""

    def __init__(self, kind: str, path: str, detail: str) -> None:
        self.kind = kind
        self.path = path
        self.detail = detail

    def __str__(self) -> str:
        return f"  {self.kind}: {self.path} -- {self.detail}"


def compare_shapes(
    mock_val: Any,
    real_val: Any,
    path: str = "",
) -> list[Mismatch]:
    """Recursively compare two JSON values and return mismatches.

    Compares keys and types for objects, element shapes for arrays,
    and type names for scalars.
    """
    mismatches: list[Mismatch] = []
    mock_type = typeof(mock_val)
    real_type = typeof(real_val)

    # Special case: null in mock is a "don't care" — the real value could be anything
    if mock_val is None:
        return mismatches

    # Top-level type mismatch
    if mock_type != real_type:
        mismatches.append(
            Mismatch(
                "TYPE_MISMATCH",
                path or "<root>",
                f"mock={mock_type}, real={real_type}",
            )
        )
        return mismatches

    if mock_type == "object":
        mock_keys = set(mock_val.keys())
        real_keys = set(real_val.keys())

        extra_in_mock = mock_keys - real_keys
        missing_in_mock = real_keys - mock_keys

        for k in sorted(extra_in_mock):
            child_path = f"{path}.{k}" if path else k
            # Check if this might be a rename (same type exists under different key)
            possible_rename = _find_rename_candidate(k, mock_val[k], missing_in_mock, real_val)
            if possible_rename:
                mismatches.append(
                    Mismatch(
                        "KEY_RENAME",
                        child_path,
                        f"mock has '{k}', real has '{possible_rename}' (same type: {typeof(mock_val[k])})",
                    )
                )
            else:
                mismatches.append(
                    Mismatch("EXTRA_IN_MOCK", child_path, f"key '{k}' exists in mock but not in real response")
                )

        for k in sorted(missing_in_mock):
            child_path = f"{path}.{k}" if path else k
            # Skip if already reported as rename
            if any(m.kind == "KEY_RENAME" and f"'{k}'" in m.detail for m in mismatches):
                continue
            mismatches.append(
                Mismatch("MISSING_IN_MOCK", child_path, f"key '{k}' exists in real response but not in mock")
            )

        # Recurse into shared keys
        for k in sorted(mock_keys & real_keys):
            child_path = f"{path}.{k}" if path else k
            mismatches.extend(compare_shapes(mock_val[k], real_val[k], child_path))

    elif mock_type == "array":
        # Compare first element shapes if both non-empty
        if len(mock_val) > 0 and len(real_val) > 0:
            elem_path = f"{path}[]" if path else "[]"
            mismatches.extend(compare_shapes(mock_val[0], real_val[0], elem_path))
        # If mock is empty but real is non-empty, note it (informational, not a mismatch)
        # If both are empty, shapes trivially match

    return mismatches


def _find_rename_candidate(
    mock_key: str,
    mock_value: Any,
    candidate_keys: set[str],
    real_obj: dict[str, Any],
) -> str | None:
    """Check if a missing mock key was likely renamed in the real response.

    Heuristic: same base type and similar key name (e.g. watchlist_id -> id).
    """
    mock_t = typeof(mock_value)
    for ck in candidate_keys:
        if typeof(real_obj[ck]) == mock_t:
            # Check if one is a suffix/prefix of the other
            if mock_key.endswith(ck) or ck.endswith(mock_key):
                return ck
            if mock_key.startswith(ck) or ck.startswith(mock_key):
                return ck
    return None


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    """Run the contract alignment check. Returns exit code."""
    print("=" * 60)
    print("  Contract Alignment Report")
    print("  Mock fixtures vs. live S9 API responses")
    print("=" * 60)
    print()

    # Step 1: Read and parse mock file
    if not os.path.isfile(MOCK_FILE):
        print(f"ERROR: Mock file not found: {MOCK_FILE}")
        return 2

    with open(MOCK_FILE) as f:
        source = f.read()

    mock_constants = parse_mock_constants(source)
    print(f"Parsed {len(mock_constants)} mock constants from api-mocks.ts")
    for name in sorted(mock_constants):
        print(f"  - {name}")
    print()

    # Step 2: Get auth token
    token = get_dev_token()
    if not token:
        print("ERROR: Could not obtain dev-login token. Is S9 running?")
        print("  Falling back to shape-only analysis (mock parsing without live comparison).")
        print()
        _print_mock_shapes(mock_constants)
        return 2

    print(f"Obtained dev-login token (length={len(token)})")
    print()

    # Step 3: Compare each endpoint
    stats = {"checked": 0, "matching": 0, "mismatched": 0, "skipped": 0}

    # Named constant endpoints
    for const_name, method, path, body in ENDPOINT_MAP:
        mock_val = mock_constants.get(const_name)
        if mock_val is None:
            print(f"Endpoint: {method} {path}")
            print(f"  SKIP: Could not parse mock constant '{const_name}'")
            print()
            stats["skipped"] += 1
            continue

        _check_endpoint(method, path, const_name, mock_val, token, body, stats)

    # Inline mock endpoints
    for label, (method, path, mock_val) in INLINE_MOCKS.items():
        _check_endpoint(method, path, f"<inline:{label}>", mock_val, token, None, stats)

    # Step 4: Summary
    print()
    print("=" * 60)
    print("  Summary")
    print("=" * 60)
    print(f"  Endpoints checked:              {stats['checked']}")
    print(f"  Matching:                        {stats['matching']}")
    print(f"  Mismatched:                      {stats['mismatched']}")
    print(f"  Skipped (unavailable/error):     {stats['skipped']}")
    print()

    if stats["mismatched"] > 0:
        print("RESULT: FAIL -- mock drift detected")
        return 1
    if stats["checked"] == 0:
        print("RESULT: WARN -- no endpoints could be checked")
        return 2
    print("RESULT: PASS -- all checked endpoints match")
    return 0


def _check_endpoint(
    method: str,
    path: str,
    mock_label: str,
    mock_val: Any,
    token: str,
    body: dict[str, Any] | None,
    stats: dict[str, int],
) -> None:
    """Compare a single mock against the live API and print results."""
    display_path = path.split("?")[0] if "?" in path else path
    print(f"Endpoint: {method} {display_path}")
    print(f"  Mock source: {mock_label}")

    status, real_val = call_endpoint(method, path, token, body)

    if status == -1:
        print("  SKIP: Connection refused (endpoint unavailable)")
        print()
        stats["skipped"] += 1
        return

    if status < 200 or status >= 300:
        print(f"  SKIP: HTTP {status} (cannot compare error response shape)")
        print()
        stats["skipped"] += 1
        return

    if real_val is None:
        print("  SKIP: Response body was not valid JSON")
        print()
        stats["skipped"] += 1
        return

    stats["checked"] += 1

    # Print key summaries
    mock_keys = _summarize_keys(mock_val)
    real_keys = _summarize_keys(real_val)
    print(f"  Mock keys: {mock_keys}")
    print(f"  Real keys: {real_keys}")

    # Compare shapes
    mismatches = compare_shapes(mock_val, real_val)

    if not mismatches:
        print("  PASS: Shape matches")
        stats["matching"] += 1
    else:
        stats["mismatched"] += 1
        for m in mismatches:
            print(f"  FAIL {m}")
    print()


def _summarize_keys(val: Any) -> str:
    """Return a short string summarizing the top-level keys/structure of a value."""
    if isinstance(val, dict):
        keys = list(val.keys())
        if len(keys) <= 8:
            return ", ".join(keys)
        return ", ".join(keys[:6]) + f", ... (+{len(keys) - 6} more)"
    if isinstance(val, list):
        if len(val) == 0:
            return "[empty array]"
        elem = val[0]
        if isinstance(elem, dict):
            inner = ", ".join(list(elem.keys())[:6])
            return f"[array of {{{inner}}}]"
        return f"[array of {typeof(elem)}]"
    return typeof(val)


def _print_mock_shapes(mock_constants: dict[str, Any]) -> None:
    """Fallback: print the parsed mock shapes without live comparison."""
    print("--- Mock shapes (no live comparison) ---")
    print()
    for name, val in sorted(mock_constants.items()):
        print(f"  {name}:")
        flat = flatten_shape(extract_shape(val))
        for path_key, type_name in sorted(flat.items()):
            print(f"    {path_key}: {type_name}")
        print()


if __name__ == "__main__":
    sys.exit(main())
