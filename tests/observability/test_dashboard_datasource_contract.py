"""Contract test for Grafana dashboard datasource UIDs.

Invokes scripts/check_dashboard_datasource_uids.py and asserts exit code 0.
Includes a negative test using a tmp dashboard with a bogus UID.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_dashboard_datasource_uids.py"
DASH_DIR = REPO_ROOT / "infra" / "grafana" / "dashboards"


@pytest.mark.skipif(not DASH_DIR.is_dir(), reason="infra/grafana/dashboards/ not checked out")
def test_dashboards_declare_valid_datasource_uids() -> None:
    """Run the contract script against the live repo dashboards directory."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"check_dashboard_datasource_uids.py failed:\n" f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


@pytest.mark.skipif(not DASH_DIR.is_dir(), reason="infra/grafana/dashboards/ not checked out")
def test_dashboard_with_bogus_uid_fails(tmp_path: Path) -> None:
    """Negative: a dashboard JSON referencing an unknown UID must trigger exit 1."""
    bad_dash = tmp_path / "bad.json"
    bad_dash.write_text(
        json.dumps(
            {
                "title": "bad",
                "panels": [
                    {
                        "title": "broken-panel",
                        "datasource": {"type": "prometheus", "uid": "does-not-exist"},
                    }
                ],
            }
        )
    )
    env = os.environ.copy()
    env["WORLDVIEW_DASHBOARDS_DIR"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 1, f"expected exit 1, got {result.returncode}: {result.stdout}"
    assert "does-not-exist" in result.stdout
