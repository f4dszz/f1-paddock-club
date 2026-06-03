# F1 Evals — Benchmark Substrate

This directory is a **measurement layer**. It does not change how the product
works; it defines how we will later score an agent-orchestration system on real
F1 tasks with an objective backstop.

## SUT vs Substrate

- **System Under Test (SUT):** `complex-harness` — the outer orchestration layer
  that frames a goal, picks a mode chain (planning / implementation /
  verification / audit / replay), and drives `harness-workflow`
  (executor + reviewer mailbox protocol). The SUT is **not** exercised by this
  task; we are only building the rig it will run against.
- **Substrate (this repo):** `f1-paddock-club` — a stable multi-agent product
  with a real, runnable test suite and crisp invariants in `CLAUDE.md`. The
  substrate supplies fixed tasks and an objective pass/fail signal so SUT runs
  can be scored without relying on opinion alone.

## Why this works as a benchmark

Every golden task is seeded from an **existing** f1 test or spec. The test is
the non-negotiable objective signal: a SUT run either makes the named check pass
or it does not. Subjective rubric dimensions and cost are reported **alongside**
that signal, never folded into it.

## Layout

- `rubric.md` — three-part scoring: subjective dims, mandatory objective signal,
  cost axis. Reported separately, never blended.
- `golden/` — exactly three fixed tasks (`G-001`, `G-002`, `G-003`), each naming
  a real check that must pass.
- `experiment-template.md` — one A/B run, one variable changed.
- `decision-log.md` — append-only hypothesis / observation / cost / decision.
- `runs/` — captured run records, including the baseline of the substrate suite.

## What "objective backstop" means here

The substrate's own suite is green before any SUT run. `runs/` holds that
baseline. A SUT run is only meaningful if the substrate was passing first, so the
baseline is the reference point every experiment is measured against.

## Scope discipline

- Additive only. This layer never edits product code, existing tests, the
  strict-harness protocol, or `.harness/`.
- The benchmark itself (running `complex-harness` over these tasks) is a **later**
  task. This directory is the rig, not a results set.
