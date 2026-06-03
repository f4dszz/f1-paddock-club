---
type: run
kind: retrospective-real-workflow-run
date: 2026-05-27
sut: harness-workflow (real execution observed in .harness/tasks/T-001/)
variant: B (harness-workflow — executor + reviewer mailbox)
substrate_commit_at_scoring: 1312439 (T-001 R10 changes; superseded mid-session by 8797197)
baseline_reference: docs/evals/runs/2026-05-27-baseline-check-local.md
golden_tasks_covered: G-001, G-002, G-003
---

# Retrospective — T-001 R10 as a real harness-workflow run

This is **not** a synthetic benchmark launch. It is a scoring of an actual,
already-completed harness-workflow execution sitting in `.harness/tasks/T-001/`,
read through the lens of `docs/evals/rubric.md`. The objective signal was
verified by the baseline run; subjective dims are anchored in mailbox excerpts;
cost is the literal round/elapsed count from the mailbox.

Three rubric parts reported separately, never blended.

## Run trace (what happened)

- **R8 (2026-05-18T08:59Z) — Reviewer: Rejected.** 4 findings against `85cbd78`
  + README-only `a3eb80b`: (F1) CI lane doesn't gate the full deterministic
  Playwright set; (F2) no Playwright for unpriced/incomplete or explainability;
  (F3) CI never invokes `scripts/check-local.sh` as the durable contract;
  (F4) E2E lane has no cache isolation and no executable no-network proof.
  5 non-negotiable fixes.
- **R9 (2026-05-18T09:32Z, +33 min) — Reviewer: Partially Accepted.** Narrowed
  to 6 NN constraints with reviewer-side resolutions, told executor to implement
  directly (no further plan-only round). Key R9 language enforcing A4:
  > "Do not weaken this to a synthetic UI-only assertion." (NN2)
  > "Log grep may be an additional check, not the primary proof." (NN5)
- **R10 (2026-05-27T07:28Z, +9 days) — Executor: changes committed `1312439`.**
  15 files +489/-32, 1 fused commit. Each of the 6 NN answered with a
  4-field response (Stance / Reason / Action / evidence). Calendar-drift
  surfaced as a separate flag, not silently folded in. Owner returned to
  reviewer.

The R10 deliverables map 1:1 onto our golden tasks:

| Golden | Objective check | R10 artifact |
| --- | --- | --- |
| G-001 | `frontend/e2e/quote_incomplete.spec.js` | NN2 — new spec + `tickets.py` price=0 stub gated by `APP_ENV=test + LLM_STUB_MODE=1`; trace.budget_final now carries `quote_complete` + `missing_price_categories` |
| G-002 | `backend/tests/test_rationale.py` + `frontend/e2e/explain.spec.js` | NN3 — new explain spec, 4 testids on ExplainabilityPanel + 1 on the affordance, real "i" click, asserts reasons + `Mock data` source path |
| G-003 | `backend/tests/test_outbound_egress.py` + `test_cache_bypass.py` | NN4 + NN5 — `_cache.py` `_bypass_cache()` short-circuit under `APP_ENV=test`; socket monkeypatch test with non-vacuous tickets/transport/hotel assertion |

## Part A — Subjective dimensions (1–5)

Each score is justified with a mailbox excerpt or behavior, not vibes.

| Dim | Score | Justification |
| --- | --- | --- |
| **A1 Correctness** | **5** | All 6 R9 NN items resolved in one commit; the named tests exist and pass (see Part B). R10 §"Test evidence": check-local 7/7, default e2e 3/3 in 2.6s, full e2e 6/6 in 4.1s. |
| **A2 Evidence quality** | **5** | Every claim carries either a SHA (`1312439`), a file path with line range (e.g. `backend/main.py` `_build_trace_events`, `frontend/components/ResultCard.jsx:67-68`), or a counted test result. Reviewer R8 verified before issuing the verdict ("Verified during review: check-local 7/7; e2e 2/2; full e2e 4/4") — the mailbox itself enforces evidence. |
| **A3 Boundary clarity** | **5** | R10 explicitly marks calendar drift as **out of R8/R9 scope** but mandatory for CI green, surfaces it as a side-flag with reasoning, and offers a stand option (Monaco fallback) rather than silently absorbing scope. NN3 added "focused additive" testids rather than refactoring panel structure. No edits to closed product surfaces unrelated to the 6 NN. |
| **A4 No over-promising** | **5** | The whole R8→R9→R10 arc is anti-over-promising: R8 caught docs claiming Phase 4.6 CI-complete when CI only ran smoke; R9 forced an executable egress assertion ("log grep may be an additional check, not the primary proof"); R10 honored — "log grep dropped as primary proof per ruling" — and ordered docs **after** real green: "Docs updated last in the working tree, after both check-local 7/7 and full E2E 6/6 went green locally." This is exactly the substrate invariant the rubric is meant to detect. |

Composite A is reported per-dim, not averaged. (Per rubric: "Reported
separately. Never blended into a single number.")

## Part B — Mandatory objective signal (PASS / FAIL)

| Golden | Check | Command (deterministic lane) | Result in this session |
| --- | --- | --- | --- |
| G-001 | `frontend/e2e/quote_incomplete.spec.js` | `E2E_INCLUDE_REFINE=1 LLM_STUB_MODE=1 ./scripts/e2e-local.sh` | **PASS** per R10 evidence (1/1 in the full lane 6/6); **NOT re-run in this session** — the sandbox blocked `e2e-local.sh` (exit 126 "Operation not permitted"). Not a regression; an environment limit. |
| G-002 (backend half) | `backend/tests/test_rationale.py` | `unittest discover` via `check-local.sh` step 3 | **PASS** — re-run by me in baseline: all 8 `RationaleBuilderTests` cases ok. |
| G-002 (frontend half) | `frontend/e2e/explain.spec.js` | default `./scripts/e2e-local.sh` lane | **PASS** per R10 evidence (1/1 in default 3/3); not re-run in this session (sandbox). |
| G-003 (egress) | `backend/tests/test_outbound_egress.py` | `unittest` via `check-local.sh` step 3 | **PASS** — re-run by me in baseline: `test_plan_trip_with_empty_keys_makes_zero_outbound_attempts` ok. |
| G-003 (cache) | `backend/tests/test_cache_bypass.py` | `unittest` via `check-local.sh` step 3 | **PASS** — re-run by me in baseline: both `test_test_env_bypasses_read_and_write` + `test_non_test_env_still_caches` ok. |

**Non-vacuous anchors observed (so PASS is not from an early abort):**
- G-001: post-selection panel contains "Your selected total" **and** "Incomplete
  quote" **and** "Tickets"; debug trace contains `"quote_complete":false`.
- G-002: panel asserts `Tag: VIP` **and** `Pit lane + podium` **and** `Mock data`
  — content, not just dialog presence.
- G-003: egress test asserts `attempts == []` **and** `result.get("tickets" /
  "transport" / "hotel")` truthy; cache test asserts `calls["n"] == 3` under
  test env vs `== 1` otherwise.

**Aggregate objective signal: PASS across G-001, G-002, G-003** — verified by
the baseline (backend half) and by R10's self-reported evidence (E2E half;
sandbox-blocked re-run).

## Part C — Cost (raw, not normalized)

| Axis | Value | Source |
| --- | --- | --- |
| **Mailbox rounds (R8→R10 arc)** | 3 reviewer rounds (R8 Rejected, R9 Partially Accepted, R10 changes-pending) | `.harness/tasks/T-001/mailbox/{reviewer,executor}-to-*.md` |
| **Full task rounds (since open)** | R1 / R2 / R3 / R4 / R5 / R6 / R7 / R8 / R9 / R10 — 10 reviewer rounds, ~5 executor commits along the way (`f0936b8`, `85cbd78`, `a3eb80b`, `1312439`, plus pre-R4 history) | mailbox + git log |
| **Elapsed wall-time (R8→R10)** | ~9 days (2026-05-18T08:59Z → 2026-05-27T07:28Z); R8→R9 = 33 min (verdict turnaround), R9→R10 = ~9 days (implementation + local verification before commit) | mailbox `HANDOFF` timestamps |
| **Tokens (in/out/cache)** | **not instrumented** in `.harness/` — no telemetry surfaced here. Mark as a substrate gap for future runs if cost-per-token comparison matters. | n/a |
| **Diff size** | 15 files, +489 / −32 (one fused R10 commit) | `git show --stat 1312439` |

Cost is **within-run** here; the A vs B comparison the rubric calls for (single
agent vs harness) will come later, and only then is cost compared across
variants on the same task.

## Reported shape (per rubric)

```
Task: G-001  | A: A1=5 A2=5 A3=5 A4=5  | B: PASS (quote_incomplete.spec.js)               | C: rounds(R8→R10)=3 elapsed≈9d
Task: G-002  | A: A1=5 A2=5 A3=5 A4=5  | B: PASS (test_rationale + explain.spec.js)       | C: rounds(R8→R10)=3 elapsed≈9d
Task: G-003  | A: A1=5 A2=5 A3=5 A4=5  | B: PASS (test_outbound_egress + test_cache_bypass)| C: rounds(R8→R10)=3 elapsed≈9d
```

(Same A/B/C row repeats because all three golden tasks were produced by the same
fused R10 commit; the workflow run is one, the rubric application is per-task.)

## What this run shows about the SUT category (harness-workflow vs single-agent)

Not a controlled A/B, but a **directional** observation worth logging:

- The reviewer/executor protocol catches over-promising at R8 (4 real findings)
  that a single-agent pass would likely have shipped as-is. The cost is rounds
  and wall-time; the benefit is a tighter A4 score and a non-vacuous Part B.
- The 4-field per-NN response shape (Stance / Reason / Action / evidence)
  in R10 is what produces the high A2 — the protocol structures evidence.
- The reviewer's "do not weaken to synthetic" line at R9 is the rubric's A4
  enforced inside the workflow itself, not bolted on at scoring time.

The A vs B contrast hypothesis to test later: would a single-agent run on the
same R8 starting point produce green tests faster (lower C) but with weaker A4
(over-promising docs / log-grep-only proof)? That is the next experiment per
`experiment-template.md`.

## Limits of this retrospective

- **Not a controlled experiment.** No held-out variable; this is observational.
  Real A/B remains future work.
- **No token telemetry.** Part C is rounds + wall-time + diff size only.
- **E2E re-run blocked by sandbox** in this session — R10's E2E evidence
  (6/6 in 4.1s) is trusted but not independently re-verified here.
- **Reviewer R10 verdict still pending** (`reviewer-to-executor.md` still ends
  at the R9 entry of 2026-05-18T09:32Z). Scoring may need a small revision if
  R10 is rejected — recorded as an open item for monitoring.
