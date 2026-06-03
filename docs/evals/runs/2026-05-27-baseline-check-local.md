---
type: run
kind: baseline
date: 2026-05-27
substrate_commit: a3eb80b (working tree, additive docs/evals only)
gate: scripts/check-local.sh
result: PASS
---

# Baseline — substrate suite green

This records the substrate's own suite passing **before** any SUT run. Every
later experiment is measured against this reference. No product code or
`.harness/` was modified to produce it.

## Command

```bash
scripts/check-local.sh
```

## Result

- **Exit:** 0 (PASS)
- **Wall-time:** ~6s (full local gate; npm deps already cached)
- **Backend unit tests:** `Ran 86 tests in 0.234s` → `OK`
- **Frontend build:** vite build OK (`dist/assets/index-*.js 242.50 kB`)
- **Dependency audit:** `found 0 vulnerabilities`

All 7 gate steps ran:

```
[1/7] Agent guideline sync
[2/7] Backend compile
[3/7] Backend unit tests        -> Ran 86 tests in 0.234s / OK
[4/7] URL normalizer skill tests
[5/7] Frontend clean install    -> added 25 packages, audited 26
[6/7] Frontend build            -> vite build OK
[7/7] Frontend dependency audit -> 0 vulnerabilities
```

## Golden-task objective signals confirmed in this baseline

The three golden tasks' backend source modules all pass in step [3/7]:

- `test_outbound_egress.OutboundEgressTests.test_plan_trip_with_empty_keys_makes_zero_outbound_attempts` … ok  (G-003)
- `test_cache_bypass.CacheBypassTests.test_test_env_bypasses_read_and_write` … ok  (G-003)
- `test_cache_bypass.CacheBypassTests.test_non_test_env_still_caches` … ok  (G-003)
- `test_rationale.RationaleBuilderTests.*` (8 tests) … ok  (G-002 backend half)

## Frontend E2E lane (default no-key lane)

Command: `scripts/e2e-local.sh` (runs `smoke.spec.js` + `explain.spec.js`;
`quote_incomplete.spec.js` stays gated behind `E2E_INCLUDE_REFINE=1`).

- Chromium + headless-shell browsers present in `~/Library/Caches/ms-playwright`
  (`chromium-1217`), so the lane is feasible in this environment.
- **Result:** see `e2e-meta` below — captured separately because it spins up live
  dev servers, unlike the hermetic backend lane.

**Attempted, blocked by sandbox:** `scripts/e2e-local.sh` returned exit 126
(`Operation not permitted`) in this session — the sandbox denies spawning the
live backend/frontend dev servers the script needs. Wall-time 0s; the suite never
started, so this is **an environment restriction, not a test regression**. The
specs themselves are present and wired (see `playwright.config.js`). Re-run
outside the sandbox with `./scripts/e2e-local.sh` to capture a green E2E baseline.

## Notes

- `quote_incomplete.spec.js` (G-001 objective signal) requires
  `E2E_INCLUDE_REFINE=1 LLM_STUB_MODE=1`; it is intentionally **not** part of the
  default lane and was not run in this baseline. Its existence and gating are
  verified; its green run is left for the G-001 experiment.
