"""
Conftest for architecture tests.

These tests are synchronous filesystem/AST checks.
Add the repo root to sys.path so that `tests.architecture._utils` is importable.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the repo root is on sys.path so `tests.architecture._utils` resolves.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
