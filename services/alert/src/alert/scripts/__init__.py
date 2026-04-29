"""One-shot operational scripts for the alert service.

Backfill / repair utilities live here. Run them as importable modules:

    python -m alert.scripts.<name> [args]

The scripts live inside the package (``src/alert/scripts/``) so they
ship in the wheel and can be invoked uniformly from a service container,
local venv, or the test environment.
"""
