#!/usr/bin/env python3
"""Contract test: every datasource.uid in a dashboard JSON must be declared in
infra/grafana/provisioning/datasources/datasources.yml.

Fails fast with a descriptive message; intended to be invoked from CI / pytest.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DASH_DIR = REPO_ROOT / "infra" / "grafana" / "dashboards"
DEFAULT_DATASOURCES = REPO_ROOT / "infra" / "grafana" / "provisioning" / "datasources" / "datasources.yml"


def _collect_uids(node: object, found: list[tuple[str, str]], path: str = "") -> None:
    """Recursively walk a JSON tree and collect every (panel_title, uid) pair."""
    if isinstance(node, dict):
        ds = node.get("datasource")
        if isinstance(ds, dict) and isinstance(ds.get("uid"), str):
            title = node.get("title") if isinstance(node.get("title"), str) else path
            found.append((title or "(no title)", ds["uid"]))
        for k, v in node.items():
            _collect_uids(v, found, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _collect_uids(item, found, f"{path}[{i}]")


def main() -> int:
    dash_dir = Path(os.environ.get("WORLDVIEW_DASHBOARDS_DIR", str(DEFAULT_DASH_DIR)))
    ds_file = Path(os.environ.get("WORLDVIEW_DATASOURCES_FILE", str(DEFAULT_DATASOURCES)))
    if not dash_dir.is_dir() or not ds_file.is_file():
        print(f"SKIP: missing {dash_dir} or {ds_file}", file=sys.stderr)
        return 0
    declared = {
        d["uid"]
        for d in (yaml.safe_load(ds_file.read_text()) or {}).get("datasources", [])
        if "uid" in d
    }
    checked: list[Path] = []
    all_uids: set[str] = set()
    for dash in sorted(dash_dir.glob("*.json")):
        checked.append(dash)
        data = json.loads(dash.read_text())
        found: list[tuple[str, str]] = []
        _collect_uids(data, found)
        for title, uid in found:
            # Templated UIDs like "${datasource}" are runtime-resolved — skip.
            if uid.startswith("$") or uid.startswith("${"):
                continue
            all_uids.add(uid)
            if uid not in declared:
                print(f"FAIL: {dash}:{title} references uid={uid} not in {sorted(declared)}")
                return 1
    print(f"OK: {len(checked)} dashboards, {len(all_uids)} unique datasource refs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
