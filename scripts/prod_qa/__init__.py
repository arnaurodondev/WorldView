"""worldview prod-QA harness — a durable, read-only production QA suite.

Extends the philosophy of ``scripts/prod_e2e_smoke.py`` with LARGE, granular,
per-service functional assertions so any small regression on the live Hetzner
single-node k3s deploy is detectable on a re-run.

Run with ``python3 -m scripts.prod_qa.run`` (see run.py for options).
"""
