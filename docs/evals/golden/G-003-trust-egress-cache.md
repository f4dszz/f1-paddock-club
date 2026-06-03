---
id: G-003
title: Deterministic lane makes zero outbound egress and bypasses disk cache
mode_chain: audit -> verification
objective_check: backend/tests/test_outbound_egress.py + backend/tests/test_cache_bypass.py
invariant: "No network calls during the deterministic test lane; no stale cache pollution under APP_ENV=test."
---

# G-003 — Trust: egress + cache isolation

## Goal

Confirm (audit) and prove (verification) that the deterministic test lane is
hermetic: `plan_trip` with empty provider keys attempts **zero** remote sockets,
and the `@cached` decorator neither reads nor writes disk under `APP_ENV=test`
while still caching normally otherwise.

## Mode chain exercised

`audit -> verification`. Audit traces the socket and cache surfaces to confirm the
guards exist where claimed. Verification runs the two executable assertions that
fail loudly if egress or cache I/O leaks into the deterministic lane.

## Input / material paths

- `backend/tests/test_outbound_egress.py` — monkeypatches `socket.connect` /
  `create_connection`, allows loopback only, asserts no remote attempt during
  `plan_trip`, and checks the plan is non-vacuously populated.
- `backend/tests/test_cache_bypass.py` — asserts `_load`/`_save` are not called
  under `APP_ENV=test`, and that caching still works when `APP_ENV` is unset.
- `backend/tools/_cache.py` — the `cached` decorator + `APP_ENV` short-circuit.

## Objective acceptance (must pass)

Both backend unit tests pass (same discovery as `check-local.sh` step 3):

```bash
cd backend && python -m unittest tests.test_outbound_egress tests.test_cache_bypass -v
```

Non-vacuous anchors: egress test asserts `attempts == []` **and**
`result.get("tickets"/"transport"/"hotel")` are truthy (so the empty-attempts
pass cannot come from an early abort); cache test asserts `calls["n"] == 3` under
test env (every call ran) and `== 1` with cache enabled.

## Rubric dims to score

- A4 No over-promising (hermeticity is the claim), A2 Evidence quality
  (executable assertion, not a log grep), A1 Correctness.
- Part B: both tests above. Part C: tokens / rounds / wall-time.

## Non-goals

- Do not loosen the loopback allowlist or the `APP_ENV=test` short-circuit.
- Do not add real provider calls to "improve" coverage.
- Cache file cleanup in the non-test path must stay (avoid polluting the repo).
