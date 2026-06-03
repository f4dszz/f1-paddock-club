---
type: experiment-template
rule: one A/B run changes exactly ONE variable
---

# Experiment Template

Copy this into `runs/<date>-<task>-<A>vs<B>.md` for each comparison. Change
**one** variable between A and B; everything else (task, env, model, seed) stays
fixed. Report the three rubric parts separately.

## Header

- **Experiment ID:** `<date>-<task>-<A>vs<B>`
- **Golden task:** `G-00x` (link)
- **Variable under test:** _the single thing that differs_
- **Held constant:** task text, substrate commit, model, provider keys (empty),
  deterministic lane env
- **Baseline reference:** `runs/<baseline file>` (substrate must be green first)

## Planned first comparison

- **A = single-agent (no harness):** one agent, no executor/reviewer protocol.
- **B = harness-workflow:** executor + reviewer mailbox protocol.

Only A vs B is in scope for the first run. **Later, not now:** C =
`complex-harness` (full mode-chain orchestration), D = C + MCP tools. Do not run
C/D until A/B has a recorded result.

## Per-variant record

For each of A and B:

### Part A — Subjective (1–5, one-line justification each)
- A1 Correctness:
- A2 Evidence quality:
- A3 Boundary clarity:
- A4 No over-promising:

### Part B — Objective signal (PASS / FAIL)
- Check: `<the golden task's named test>`
- Command:
- Exit status:
- Non-vacuous anchor observed:

### Part C — Cost (raw)
- Tokens (in / out / cache):
- Rounds:
- Wall-time (s):

## Comparison summary

| | A1 | A2 | A3 | A4 | B (obj) | tokens | rounds | wall |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A |  |  |  |  |  |  |  |  |
| B |  |  |  |  |  |  |  |  |

## Outcome

- What the single variable changed (kept separate per axis):
- Decision logged in `decision-log.md`? (yes/no + entry id)
