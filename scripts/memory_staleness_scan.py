#!/usr/bin/env python3
"""
memory_staleness_scan.py — Scan project memory files for staleness.

Reads frontmatter from all .md files in the Claude memory directory and
flags entries that are older than a configurable threshold or have been
explicitly superseded. Helps keep MEMORY.md under the 200-line cap.

Usage:
    python3 scripts/memory_staleness_scan.py
    python3 scripts/memory_staleness_scan.py --days 30
    python3 scripts/memory_staleness_scan.py --memory-dir /path/to/memory
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path


def _default_memory_dir() -> Path:
    """Derive the Claude memory dir from the current repo path (works for any checkout location)."""
    repo_root = Path(__file__).parent.parent.resolve()
    slug = str(repo_root).replace("/", "-").lstrip("-")
    return Path.home() / ".claude/projects" / slug / "memory"


MEMORY_DIR_DEFAULT = _default_memory_dir()
DEFAULT_STALE_DAYS = 60
ENTRYPOINT_MAX_LINES = 200
ENTRYPOINT_MAX_BYTES = 25_000


def parse_frontmatter(text: str) -> dict[str, str]:
    """Extract YAML frontmatter fields from a Markdown file."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fm_block = text[4:end]
    result: dict[str, str] = {}
    for line in fm_block.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result


def parse_date(value: str) -> datetime | None:
    """Parse ISO date string to UTC datetime."""
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def scan_memory_dir(memory_dir: Path, stale_days: int) -> None:
    if not memory_dir.exists():
        print(f"Memory directory not found: {memory_dir}")
        sys.exit(1)

    now = datetime.now(tz=UTC)
    stale_files: list[tuple[str, int, str]] = []  # (path, age_days, type)
    ok_files: list[str] = []
    no_frontmatter: list[str] = []

    md_files = sorted(memory_dir.rglob("*.md"))
    for md_file in md_files:
        if md_file.name == "MEMORY.md":
            continue  # index file, check separately
        if "archive" in md_file.parts:
            continue  # archived files are intentionally old

        text = md_file.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)

        if not fm:
            no_frontmatter.append(str(md_file.relative_to(memory_dir)))
            continue

        mem_type = fm.get("type", "unknown")
        last_accessed_str = fm.get("last_accessed", "")
        created_str = fm.get("created", "")

        # Use last_accessed if present, fall back to created, fall back to file mtime
        ref_date: datetime | None = None
        if last_accessed_str:
            ref_date = parse_date(last_accessed_str)
        if ref_date is None and created_str:
            ref_date = parse_date(created_str)
        if ref_date is None:
            mtime = md_file.stat().st_mtime
            ref_date = datetime.fromtimestamp(mtime, tz=UTC)

        age_days = (now - ref_date).days
        rel_path = str(md_file.relative_to(memory_dir))

        if age_days > stale_days:
            stale_files.append((rel_path, age_days, mem_type))
        else:
            ok_files.append(f"  ✓ {rel_path} ({age_days}d, type={mem_type})")

    # Check MEMORY.md size
    entrypoint = memory_dir / "MEMORY.md"
    entrypoint_warnings: list[str] = []
    if entrypoint.exists():
        ep_text = entrypoint.read_text(encoding="utf-8")
        ep_lines = ep_text.count("\n")
        ep_bytes = len(ep_text.encode("utf-8"))
        if ep_lines >= ENTRYPOINT_MAX_LINES * 0.85:
            entrypoint_warnings.append(
                f"MEMORY.md is {ep_lines} lines — approaching {ENTRYPOINT_MAX_LINES}-line cap "
                f"({ep_lines / ENTRYPOINT_MAX_LINES * 100:.0f}% full)"
            )
        if ep_bytes >= ENTRYPOINT_MAX_BYTES * 0.85:
            entrypoint_warnings.append(
                f"MEMORY.md is {ep_bytes // 1024} KB — approaching {ENTRYPOINT_MAX_BYTES // 1024} KB cap"
            )

    # Report
    print("═" * 60)
    print("  MEMORY STALENESS SCAN")
    print(f"  Threshold: {stale_days} days | Dir: {memory_dir}")
    print("═" * 60)

    if entrypoint_warnings:
        print("\n⚠  MEMORY.md SIZE WARNINGS:")
        for w in entrypoint_warnings:
            print(f"  {w}")

    if stale_files:
        print(f"\n⚠  STALE FILES ({len(stale_files)}) — older than {stale_days} days:")
        for path, age, mem_type in sorted(stale_files, key=lambda x: -x[1]):
            print(f"  ✗ {path} ({age}d, type={mem_type})")
        print("\n  Consider archiving or updating these entries.")
        print("  Archive to: memory/archive/")
    else:
        print(f"\n  ✓ No stale files found (threshold: {stale_days} days)")

    if no_frontmatter:
        print(f"\n⚠  FILES WITHOUT FRONTMATTER ({len(no_frontmatter)}):")
        for path in no_frontmatter:
            print(f"  ? {path}")
        print("  Add frontmatter with type, description, and created date.")

    if ok_files:
        print(f"\n  OK FILES ({len(ok_files)}):")
        for line in ok_files:
            print(line)

    print("\n" + "═" * 60)
    n_issues = len(stale_files) + len(no_frontmatter) + len(entrypoint_warnings)
    if n_issues > 0:
        print(f"  {n_issues} issue(s) found. Review memory directory.")
    else:
        print("  Memory is healthy.")
    print("═" * 60)

    sys.exit(1 if n_issues > 0 else 0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan memory files for staleness")
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_STALE_DAYS,
        help=f"Days threshold for staleness (default: {DEFAULT_STALE_DAYS})",
    )
    parser.add_argument(
        "--memory-dir",
        type=Path,
        default=MEMORY_DIR_DEFAULT,
        help="Path to memory directory",
    )
    args = parser.parse_args()
    scan_memory_dir(args.memory_dir, args.days)


if __name__ == "__main__":
    main()
