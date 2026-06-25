"""End-to-end tests for the api-gateway public security boundary.

These tests exercise the gateway as a black box (full middleware stack +
routers, with downstream service clients mocked) to lock the auth/tenant
boundary and the BUG-7 5xx-sanitization invariant. They are deliberately
separate from the per-route proxy unit tests: those assert plumbing; these
assert the *security contract* a client/attacker sees from outside.
"""
