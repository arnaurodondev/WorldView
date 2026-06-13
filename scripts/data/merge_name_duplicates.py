#!/usr/bin/env python3
"""Merge ticker-LESS name-based duplicate canonical_entities (FR-11).

ROOT CAUSE (see docs/audits/2026-06-13-fr11-duplicate-canonical-investigation.md):
the parallel session's ticker dedup (BP-459 Phase 3, ``merge_ticker_duplicates``)
collapsed same-TICKER ``financial_instrument`` clusters, but the LARGER residual
class is **ticker-less / name-based** duplicates that share NO ticker and NO exact
lowercased name, so none of the existing guards catch them:

  - migration 0051 ``UNIQUE(ticker) WHERE entity_type='financial_instrument'``
    never fires (NULL ticker ⇒ excluded from the partial index);
  - migration 0026 ``lower(canonical_name)`` unique index is partial
    (``WHERE entity_type != 'financial_instrument'``) — two FI rows never conflict
    on name;
  - the 0.75 trigram fuzzy pre-lookup in ``persist_enrichment`` misses because the
    surface strings score below threshold (e.g. ``similarity('spacex','spacex
    shares')`` = 0.54, ``'spacexâ'`` = 0.67, ``'spacexai'`` = 0.60).

So every news mention of "SpaceX shares" / "SpaceX stock" / "SpaceXâ" minted a
FRESH canonical, fragmenting the graph: the real hub ``SpaceX`` (9ecb9bad, degree
66) holds the meaningful edges while degree-0/1 satellites carry orphan edges,
which is the PLAN-0112 "connected but no reportable path" symptom.

WHY raw trigram misses but we still merge safely: the SpaceX-class variants are
the hub name PLUS a generic finance suffix ("shares"/"stock"/"class a common
stock") or a mojibake/glued artifact ("SpaceXâ"/"SpaceXAI").  After we strip those
suffixes and repair the mojibake tail, every variant **normalises to exactly
"spacex"** — an exact, token-superset match.  We cluster on the NORMALISED name,
not the raw surface string.

TWO TIERS (precision-first):
  * AUTO tier  — same entity_type, both ticker NULL, and the member's normalised
    name is a TOKEN-SUPERSET of the cluster hub's normalised name (hub tokens ⊆
    member tokens) AND post-normalisation trigram ≥ 0.92.  Plus an explicit
    encoding/glued-artifact sub-rule for degree≤1 satellites whose normalised name
    is the hub's normalised name + a short alpha tail ("spacexai", "spacexa").
    These are auto-merged into the hub.  ``--apply --tier auto`` is the only path
    that writes.
  * REVIEW tier — 0.80 ≤ trigram < 0.92 (or cross-type near-matches like the
    "SpaceX Starlink" PRODUCT vs SpaceX INSTRUMENT) — emitted to a CSV for HUMAN
    confirmation.  NEVER auto-merged.

SURVIVOR RULE (deterministic): highest ``node_degree.degree`` wins (the real hub —
SpaceX 9ecb9bad at degree 66); tie-break oldest ``created_at``.  Cross-type merges
are NEVER auto-performed.

RE-POINTING is delegated to the FR-13 graph-aware ``_merge_cluster`` engine from
``merge_ticker_duplicates`` (imported, not forked) — it re-points relations,
relation_evidence(_raw), claims, events, event_entities, entity_event_exposures,
narrative versions, path_insights/jobs, llm_usage_log, ticker/entity aliases, and
nlp_db.entity_mentions, AND cleans the AGE shadow graph (edge DELETE + loser-vertex
DETACH DELETE) so the merge does not recreate phantom edges.

The script is SAFE TO RE-RUN: after a successful pass a hub has absorbed its
satellites, so the next run finds no residual cluster for it.  Single transaction
per cluster (the engine commits/rolls back per cluster).

Usage:
    # Dry-run (DEFAULT): list BOTH tiers, write nothing, emit the review CSV.
    python scripts/data/merge_name_duplicates.py
    python scripts/data/merge_name_duplicates.py --entity-type financial_instrument
    # Apply ONLY the auto tier (high-precision):
    python scripts/data/merge_name_duplicates.py --apply --tier auto
    # Custom review CSV path:
    python scripts/data/merge_name_duplicates.py --review-csv /tmp/fr11_review.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

# Reuse the FR-13 graph-aware repoint engine + DSNs from the ticker script rather
# than forking it — the re-pointing surface (relations/evidence/claims/AGE/…) is
# identical; only the CLUSTERING rule differs here.  We add this directory to the
# import path so the sibling module resolves when run as a standalone script.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from merge_ticker_duplicates import (
    _INTEL_DSN,
    _NLP_DSN,
    Cluster,
    _merge_cluster,
)

# ── Normalisation knobs ──────────────────────────────────────────────────────
#
# Generic finance suffixes that carry NO entity identity — "SpaceX shares" and
# "SpaceX stock" are the SAME company as "SpaceX".  Stripped (longest-first,
# iteratively) from the END of a normalised name before clustering.  Kept
# conservative: only tokens that are unambiguously corporate/security boilerplate.
_GENERIC_SUFFIXES: tuple[str, ...] = (
    "class a common stock",
    "class b common stock",
    "class c common stock",
    "common stock",
    "ordinary shares",
    "preferred stock",
    "class a",
    "class b",
    "class c",
    "shares",
    "stock",
    "equity",
    "holdings",
    "holding",
    "group",
    "company",
    "corporation",
    "incorporated",
    "adr",
    "plc",
    "inc",
    "corp",
    "ltd",
    "llc",
    "co",
    "sa",
    "ag",
    "nv",
    "the",
)

# Trigram thresholds.  AUTO requires post-strip EXACT normalised-name equality
# (so "SpaceX shares"/"SpaceX stock"/"SpaceX Class A common stock" all collapse to
# "spacex" == hub) plus a token-superset sanity check.  REVIEW captures the
# uncertain 0.80-0.92 middle band (typos, partial overlaps) for human eyes.
_AUTO_SIM = 0.92
_REVIEW_SIM = 0.80
# Encoding/glued-artifact tail: a degree≤1 satellite whose normalised name is the
# hub's normalised name + ≤ this many trailing alpha chars ("spacex"+"ai"/"a").
_ARTIFACT_TAIL_MAX = 3
_ARTIFACT_MAX_DEGREE = 1
# CRITICAL precision guard: the artifact rule may ONLY fire when the HUB's
# normalised name is at least this long.  Without it, a short hub like "b" / "on"
# / "crc" would swallow every unrelated ticker that merely starts with those
# letters ("BGCA", "ONCO", "CRCL") — observed in the first live dry-run.  A long
# hub (≥ this) + short alpha tail is genuinely a span-bleed/mojibake artifact.
_ARTIFACT_MIN_HUB_LEN = 5


def _strip_trailing_mojibake(name: str) -> str:
    """Remove a trailing run of latin-1-supplement mojibake noise.

    GLiNER span-boundary bleed produces tails like ``SpaceXâ`` (U+00E2) or
    ``Nvidiaâ€™`` — a trailing run of chars in the U+0080-U+00FF block plus the
    smart-quote artefacts ``€™``.  We strip that tail so the clean prefix
    ("SpaceX") survives normalisation.  ASCII-only names are untouched.
    """
    # Strip a trailing run of common mojibake codepoints: latin-1 supplement
    # (U+0080-U+00FF, e.g. the bare a-circumflex), general punctuation
    # (U+2000-U+206F smart quotes/dashes), euro sign, and trademark sign.
    return re.sub("[\u0080-\u00ff\u2000-\u206f\u20ac\u2122]+$", "", name)


def normalize_name(name: str) -> str:
    """Canonicalise a surface name for clustering.

    Steps: repair the mojibake tail → NFKD-fold accents to ASCII → lowercase →
    drop non-alphanumeric punctuation → collapse whitespace → iteratively strip
    generic finance suffixes from the end.  Two names that denote the same entity
    modulo boilerplate/encoding collapse to an identical string.
    """
    s = _strip_trailing_mojibake(name)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    s = re.sub(r"\s+", " ", s).strip()
    changed = True
    while changed:
        changed = False
        for suf in _GENERIC_SUFFIXES:
            # Never strip a suffix that is the WHOLE name (else "Inc" → "").
            if s != suf and s.endswith(" " + suf):
                s = s[: -(len(suf) + 1)].strip()
                changed = True
                break
    return s


def _trigram(a: str, b: str) -> float:
    """Pure-Python pg_trgm-compatible trigram similarity on normalised strings.

    pg_trgm pads each token with two leading spaces + one trailing space and
    counts shared trigrams over the union (Jaccard).  We replicate it here so the
    tier decision is unit-testable WITHOUT a DB round-trip; the live clustering
    uses the SAME function, so dry-run counts and apply behaviour agree.
    """

    def trigrams(s: str) -> set[str]:
        if not s:
            return set()
        out: set[str] = set()
        for word in s.split(" "):
            padded = "  " + word + " "
            for i in range(len(padded) - 2):
                out.add(padded[i : i + 3])
        return out

    ta, tb = trigrams(a), trigrams(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def _is_token_superset(hub_norm: str, member_norm: str) -> bool:
    """True iff every token of the hub appears in the member (hub ⊆ member).

    "spacex" ⊆ "spacex shares" (pre-suffix-strip view) and, after stripping, the
    member collapses to "spacex" == hub → still a (degenerate) superset.  Empty
    hub is never a superset (avoids folding everything into a boilerplate-only
    name).
    """
    hub_tokens = set(hub_norm.split())
    member_tokens = set(member_norm.split())
    if not hub_tokens:
        return False
    return hub_tokens <= member_tokens


def _is_encoding_artifact(hub_norm: str, member_norm: str, member_degree: int) -> bool:
    """True for a low-degree glued/mojibake satellite of the hub.

    Catches GLiNER span bleed like "SpaceXAI" (norm "spacexai") and residual
    mojibake like "SpaceXâ" (norm "spacexa"): the hub's normalised name is a
    PREFIX of the member's, the trailing delta is ≤ ``_ARTIFACT_TAIL_MAX`` alpha
    chars, the member is a degree≤1 noise vertex, AND the hub is at least
    ``_ARTIFACT_MIN_HUB_LEN`` chars long.  The hub-length floor is essential: a
    short hub ("b"/"on"/"crc") would otherwise swallow every unrelated ticker
    that merely starts with it ("BGCA"/"ONCO"/"CRCL").  Single-token only (no
    space), so "spacex starlink" is NOT swept in here.
    """
    if member_degree > _ARTIFACT_MAX_DEGREE:
        return False
    if len(hub_norm) < _ARTIFACT_MIN_HUB_LEN:
        return False
    if " " in hub_norm or " " in member_norm:
        return False
    if not member_norm.startswith(hub_norm) or member_norm == hub_norm:
        return False
    tail = member_norm[len(hub_norm) :]
    return 0 < len(tail) <= _ARTIFACT_TAIL_MAX and tail.isalpha()


@dataclass
class NameMember:
    entity_id: str
    canonical_name: str
    entity_type: str
    degree: int
    created_at: object
    norm: str


@dataclass
class NameCluster:
    """A hub plus its auto-mergeable and review-only candidate satellites."""

    hub: NameMember
    auto: list[NameMember] = field(default_factory=list)
    review: list[tuple[NameMember, float, str]] = field(default_factory=list)  # (member, sim, reason)


def _fetch_candidates(intel: psycopg.Connection, entity_type: str | None) -> list[NameMember]:
    """Load ticker-less canonicals (optionally one entity_type) with their degree."""
    base = """
SELECT ce.entity_id, ce.canonical_name, ce.entity_type,
       COALESCE(nd.degree, 0) AS degree, ce.created_at
FROM canonical_entities ce
LEFT JOIN node_degree nd ON nd.entity_id = ce.entity_id
WHERE ce.ticker IS NULL
  {clause}
ORDER BY ce.entity_type, COALESCE(nd.degree, 0) DESC, ce.created_at
"""
    # The entity_type value is always a bound parameter — never spliced — so there
    # is no injection surface (the {clause} slot is one of two constant strings).
    sql = base.replace("{clause}", "AND ce.entity_type = %(et)s" if entity_type else "")
    rows = intel.execute(sql, {"et": entity_type} if entity_type else {}).fetchall()
    out: list[NameMember] = []
    for eid, name, etype, degree, created in rows:
        out.append(
            NameMember(
                entity_id=str(eid),
                canonical_name=name,
                entity_type=etype,
                degree=int(degree),
                created_at=created,
                norm=normalize_name(name),
            )
        )
    return out


def build_clusters(candidates: list[NameMember]) -> list[NameCluster]:
    """Group ticker-less canonicals into hub + auto/review satellites.

    Algorithm (deterministic, O(n²) within an entity_type bucket — fine for the
    few-thousand-row residual pool):
      1. Bucket by entity_type (cross-type pairs are NEVER auto-merged).
      2. Within a bucket, process by DESCENDING degree so the real hub anchors
         first; sub-bucket members by their normalised name.
      3. For each not-yet-claimed member, compare to every existing hub.  Decide
         AUTO vs REVIEW vs skip via the tier rules.
    Only clusters with at least one auto OR review satellite are returned.
    """
    by_type: dict[str, list[NameMember]] = {}
    for m in candidates:
        by_type.setdefault(m.entity_type, []).append(m)

    clusters: list[NameCluster] = []
    for members in by_type.values():
        # Highest degree first → the hub is encountered before its satellites.
        members = sorted(members, key=lambda m: (-m.degree, m.created_at))
        hubs: list[NameCluster] = []
        claimed: set[str] = set()
        for m in members:
            if m.entity_id in claimed:
                continue
            best: tuple[NameCluster, float, str, bool] | None = None  # (cluster, sim, reason, is_auto)
            for cl in hubs:
                if cl.hub.entity_id == m.entity_id or cl.hub.norm == "" or m.norm == "":
                    continue
                sim = _trigram(cl.hub.norm, m.norm)
                superset = _is_token_superset(cl.hub.norm, m.norm)
                artifact = _is_encoding_artifact(cl.hub.norm, m.norm, m.degree)
                is_auto = (sim >= _AUTO_SIM and superset) or artifact
                if is_auto:
                    reason = "token_superset" if (sim >= _AUTO_SIM and superset) else "encoding_artifact"
                    best = (cl, sim, reason, True)
                    break  # auto match wins immediately
                if sim >= _REVIEW_SIM and (best is None or sim > best[1]):
                    best = (cl, sim, "near_match", False)
            if best is not None:
                cl, sim, reason, is_auto = best
                if is_auto:
                    cl.auto.append(m)
                    claimed.add(m.entity_id)  # absorbed → cannot become its own hub
                else:
                    cl.review.append((m, sim, reason))
                    # NOT claimed: a review candidate may still anchor its own hub.
            else:
                hubs.append(NameCluster(hub=m))
        clusters.extend(cl for cl in hubs if cl.auto or cl.review)
    return clusters


def _emit_review_csv(clusters: list[NameCluster], path: Path) -> int:
    """Write the REVIEW-tier rows for human confirmation.  Returns row count."""
    rows = 0
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "hub_entity_id",
                "hub_name",
                "hub_norm",
                "hub_degree",
                "candidate_entity_id",
                "candidate_name",
                "candidate_norm",
                "candidate_degree",
                "candidate_type",
                "similarity",
                "reason",
            ]
        )
        for cl in clusters:
            for m, sim, reason in cl.review:
                w.writerow(
                    [
                        cl.hub.entity_id,
                        cl.hub.canonical_name,
                        cl.hub.norm,
                        cl.hub.degree,
                        m.entity_id,
                        m.canonical_name,
                        m.norm,
                        m.degree,
                        m.entity_type,
                        f"{sim:.3f}",
                        reason,
                    ]
                )
                rows += 1
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Merge ticker-less name-based duplicate canonical_entities (FR-11).")
    ap.add_argument("--entity-type", help="Limit to one entity_type (e.g. financial_instrument).")
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Write changes (DEFAULT is dry-run). Only the --tier is applied.",
    )
    ap.add_argument(
        "--tier",
        choices=["auto"],
        default="auto",
        help="Which tier --apply merges. Only 'auto' is auto-mergeable; review tier is CSV-only.",
    )
    ap.add_argument(
        "--review-csv",
        default="fr11_name_dedup_review.csv",
        help="Path for the review-tier (0.80-0.92 / cross-type) CSV for human confirmation.",
    )
    args = ap.parse_args()
    dry_run = not args.apply

    with (
        psycopg.connect(_INTEL_DSN) as intel,
        psycopg.connect(_NLP_DSN) as nlp,
    ):
        candidates = _fetch_candidates(intel, args.entity_type)
        clusters = build_clusters(candidates)

        review_path = Path(args.review_csv)
        review_rows = _emit_review_csv(clusters, review_path)

        auto_clusters = [cl for cl in clusters if cl.auto]
        total_auto_losers = sum(len(cl.auto) for cl in auto_clusters)

        mode = "DRY RUN — no writes" if dry_run else f"APPLY tier={args.tier}"
        print(
            f"[{mode}] scanned {len(candidates)} ticker-less canonical(s); "
            f"{len(auto_clusters)} auto cluster(s) / {total_auto_losers} auto loser(s); "
            f"{review_rows} review row(s) → {review_path}\n"
        )

        for cl in auto_clusters:
            print(
                f"HUB {cl.hub.entity_id} ({cl.hub.canonical_name!r}, norm={cl.hub.norm!r}, "
                f"type={cl.hub.entity_type}, degree={cl.hub.degree})"
            )
            for m in cl.auto:
                print(f"    AUTO-merge {m.entity_id} ({m.canonical_name!r}, norm={m.norm!r}, degree={m.degree})")
            for m, sim, reason in cl.review:
                print(f"    review     {m.entity_id} ({m.canonical_name!r}, sim={sim:.3f}, {reason})")

            loser_ids = [m.entity_id for m in cl.auto]
            # Delegate ALL re-pointing + AGE cleanup to the FR-13 engine.  Pass an
            # empty-member Cluster (the engine only reads survivor_id + loser_ids).
            counts = _merge_cluster(
                intel,
                nlp,
                Cluster(ticker="", members=[]),
                cl.hub.entity_id,
                loser_ids,
                dry_run=dry_run,
            )
            for surface, n in sorted(counts.items()):
                print(f"        {surface}: {n}")
            print()

        verb = "would be merged" if dry_run else "merged"
        print(
            f"Done. {total_auto_losers} auto-tier loser(s) {verb} across {len(auto_clusters)} cluster(s); "
            f"{review_rows} review-tier row(s) emitted to {review_path} for HUMAN review (never auto-merged)."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
