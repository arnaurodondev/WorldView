"""Admin LLM replay endpoint stub (PLAN-0055 C-4).

Minimal stub to unblock the pre-commit mypy hook on commits that don't touch
this file.  The full implementation lives in PLAN-0055 C-4 and may be
overwritten there; this stub provides only the ``router`` attribute imported
by ``nlp_pipeline.app``.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/admin", tags=["admin"])
