---
type: decision-log
format: append-only; newest first
---

# Decision Log

Each entry: hypothesis / observation / cost / decision. Append-only.

---

## D-002 — Score the real T-001 R10 run instead of launching a synthetic A/B (2026-05-27)

- **Hypothesis:** A real, completed harness-workflow execution sitting in
  `.harness/tasks/T-001/` is a stronger first data point than a synthetic A/B,
  because its objective signal is already verified by the baseline and its
  evidence (mailbox + commit) is independently inspectable.
- **Observation:** Mid-session the orchestrator advanced HEAD twice
  (`a3eb80b → 1312439 → 8797197`); `1312439` is T-001 R10. The R8→R9→R10 arc
  maps 1:1 onto G-001 / G-002 / G-003. Recorded as
  `runs/2026-05-27-T-001-R10-retrospective.md` — A1–A4 each 5/5 with mailbox
  excerpts; Part B PASS across all three (backend half re-verified in baseline,
  E2E half trusted from R10 evidence — sandbox blocked re-run);
  Part C = 3 reviewer rounds R8→R10 over ~9d elapsed, no token telemetry.
- **Cost:** Zero new agent runs; one additive `runs/` file; sandbox blocked the
  independent E2E re-run (exit 126), which is recorded honestly.
- **Decision:** Adopt this retrospective as the variant-B first data point.
  Defer variant-A (single-agent run on the same R8 starting point) until
  asked — it is the controlled-A/B follow-up, not a same-session deliverable.
  Also: instrument **tokens** before any real A/B, since `.harness/` carries no
  token telemetry today and Part C currently rests only on rounds + wall-time.
- **Monitoring:** Live polling armed (CronCreate every 20 min,
  `7,27,47 * * * *`) — will surface any new orchestrator commits, mailbox
  changes, or `docs/superpowers/` activity. 7-day auto-expiry.

---

## D-001 — Seed: substrate is a usable benchmark backstop (2026-05-27)

- **Hypothesis:** The existing f1 test suite is a strong-enough objective signal
  that we can score a later `complex-harness` benchmark on real tasks without
  blending opinion into pass/fail.
- **Observation:** Baseline `scripts/check-local.sh` is green — 86 backend unit
  tests OK in 0.234s, frontend build clean, 0 vulnerabilities, total ~6s wall
  (`runs/2026-05-27-baseline-check-local.md`). All three golden-task source
  modules (`test_outbound_egress`, `test_cache_bypass`, `test_rationale`) pass in
  that lane; the two E2E specs (`quote_incomplete`, `explain`) exist and are
  wired with documented env gates.
- **Cost:** ~6s wall for the full local gate; backend unit tests alone 0.234s —
  cheap enough to use as a per-run objective signal.
- **Decision:** Adopt the three golden tasks (G-001/002/003) as the initial
  benchmark set. Keep scoring three-part and separate. Next step is the **A/B**
  run (single-agent vs harness-workflow) per `experiment-template.md`; defer
  `complex-harness` (C) and MCP (D) until A/B has a recorded result. Do not modify
  product code or `.harness/` to make the substrate "easier".
