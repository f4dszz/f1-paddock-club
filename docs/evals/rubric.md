# Scoring Rubric

Three parts. **Reported separately. Never blended into a single number.**

A run that fails its objective signal cannot be rescued by high subjective
scores, and a cheap run that fails is not "efficient" — it is a failure that was
cheap. Keep the axes apart so a reader can see all three at once.

## Part A — Subjective dimensions (1–5 each)

Scored by a human (or a judge) reading the SUT's output and diff. 1 = absent,
3 = acceptable, 5 = exemplary. Record a one-line justification per dimension.

| Dim | Name | 1 | 5 |
| --- | --- | --- | --- |
| A1 | **Correctness** | wrong or off-task | fully solves the stated goal |
| A2 | **Evidence quality** | claims without proof | every claim backed by a runnable check, file:line, or test output |
| A3 | **Boundary clarity** | edits outside scope; touches product/.harness when forbidden | stays exactly within declared scope |
| A4 | **No over-promising** | green/"done" without verification; implies confirmed when uncertain | honest degradation/source metadata; states what was skipped |

A4 maps directly onto the substrate's own invariants — e.g. "any selected
unpriced item must produce an incomplete quote, not a green total" and "booking
links must not imply confirmed purchase". An over-promising SUT is observable.

## Part B — Mandatory objective signal (PASS / FAIL)

Each golden task names **one real, existing, runnable f1 check**. The run is a
hard PASS only if that check passes after the SUT's work; otherwise FAIL. This is
the backstop — it does not average with Part A.

- Backend checks run via `unittest` (the same discovery `scripts/check-local.sh`
  step 3 uses): `python -m unittest backend.tests.<module> -v`.
- Frontend E2E checks run via Playwright under the deterministic lane
  (`scripts/e2e-local.sh`), with the env gates each golden task names.

Record: check name, command, exit status, and the asserting line(s) that prove it
was the real signal (not a vacuous pass).

## Part C — Cost (its own axis)

Reported as raw numbers, never normalized into the score:

- **Tokens** — input + output (and cache reads if available).
- **Rounds** — executor/reviewer mailbox round-trips (or single-agent turns).
- **Wall-time** — seconds from start to objective-signal result.

Cost is compared **within** an A/B pair (same task, one variable changed), never
across different tasks.

## Reporting shape

```
Task: G-00x
A (variant): A1=_ A2=_ A3=_ A4=_  | B: PASS/FAIL (check) | C: tokens=_ rounds=_ wall=_
```

The three blocks stay visually separate on every row.
