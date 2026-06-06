"""Operational scripts for the knowledge-graph service (S7).

Each script is invocable as a module from inside the running container, e.g.::

    docker exec worldview-knowledge-graph-1 python -m scripts.backfill_path_insights

Scripts assume they run with the same env-var set as the scheduler (so we can
reuse the scheduler's wiring helpers without re-creating them per-script).
"""
