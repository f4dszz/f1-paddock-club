---
type: run
kind: walkthrough
date: 2026-05-27
purpose: hands-on demonstration of one full eval pass on one golden task
golden_task: G-003 (trust — egress + cache isolation)
sut_output_scored: T-001 R10 (commit 1312439) — only the G-003 slice (NN4 + NN5)
---

# Walkthrough — one eval pass on G-003

This file is the worked example: what running an eval on **one** golden task
**actually looks like**, end-to-end, in five small steps. It scores the same
T-001 R10 output as the broader retrospective, but only the G-003 slice
(`test_outbound_egress.py` + `test_cache_bypass.py` + `_cache.py` short-circuit).

## Step 1 — what we're testing (the invariant)

From `golden/G-003-trust-egress-cache.md`:

> "No network calls during the deterministic test lane; no stale cache pollution
> under APP_ENV=test."

Translated into two real check files: `test_outbound_egress.py` +
`test_cache_bypass.py`. **Everything else in the golden file is for humans.**

## Step 2 — Part B (objective signal), live in this walkthrough

Command actually run (project root, deterministic):

```bash
backend/.venv/bin/python -m unittest discover -s backend/tests \
  -p "test_outbound_egress.py" -v
# Ran 1 test in 0.337s — OK

backend/.venv/bin/python -m unittest discover -s backend/tests \
  -p "test_cache_bypass.py" -v
# Ran 2 tests in 0.040s — OK
```

**Result: PASS.** Wall ≈ 0.4s. The `RuntimeError: All flight data sources
exhausted` in the log is the **expected** loud-failure surface — proof the
socket monkeypatch fired, and the agent fell back to mock as designed.

**Substrate bug found during this walkthrough:** `golden/G-003-trust-egress-cache.md`
line 38 currently shows `cd backend && python -m unittest tests.test_outbound_egress …`
— that command does not run (no `tests/__init__.py`). The discover form above
works. **Fix follow-up:** patch the acceptance command in G-003's golden file.
This is the kind of thing eval catches that single-file unit tests don't.

## Step 3 — Part A (subjective), each score anchored to a citation

| Dim | Score | Anchor (file:line — quoted excerpt) |
| --- | --- | --- |
| A1 Correctness | 5 | Part B above ran green in 0.4s; both invariants hold. |
| A2 Evidence quality | 5 | `executor-to-reviewer.md` NN5 names exact monkeypatched symbols (`socket.socket.connect` + `socket.create_connection`) and the two non-vacuous anchors (`attempts == []` AND `result.get('tickets'/'transport'/'hotel')`). Claim cites code, not vibe. |
| A3 Boundary clarity | 5 | NN5 stayed in scope: one new test file, one `_bypass_cache()` helper in `_cache.py`. No drive-by refactors. |
| **A4 No over-promising** | **5** | Closed loop: `reviewer-to-executor.md:616` demanded *"Log grep may be an additional check, not the primary proof"* → R10 NN5 *"Log grep dropped as primary proof per ruling"* → I just ran the executable assertion and saw it pass. Zero gap between claim and runnable proof. |

### A4 counterfactual (the educational point)

If R10 NN5 had instead said *"Added `grep -r 'serpapi\|firecrawl' logs/` and
asserted count stays at 0"* — **same intent, different evidence framing** —
then A4 should drop to **2/5**, because:

1. It tests the log surface, not the socket surface — silent egress on another
   path is invisible to grep.
2. It is observational, not preventive. The rubric's A4 ≥ 4 calls for "honest
   degradation/source metadata"; grep provides neither.
3. R9 explicitly banned this as primary proof.

**Same code paths, two evidence framings, 3-point A4 swing.** That is the
rubric working as a sharp instrument, not a flat 1–5 dial.

## Step 4 — Part C (cost), raw numbers only

| Axis | Value |
| --- | --- |
| Rounds in the relevant arc (R8 → R9 → R10) | 3 reviewer rounds |
| Wall-time R8 → R10 | ~9 days (R8→R9 was 33 min verdict turnaround; R9→R10 was implementation + local verify) |
| Wall-time of the objective check itself | 0.377s |
| Diff for the G-003 slice (estimate from R10 file list) | `_cache.py` +13, `test_cache_bypass.py` +82 new, `test_outbound_egress.py` +143 new → ≈ +238 lines for this slice |
| Tokens | not instrumented (substrate gap) |

## Step 5 — what this walkthrough exposed (the learning to log)

1. **Substrate bug** — G-003's acceptance command is wrong; needs patching.
   By rubric A2's own definition, **this walkthrough should score G-003's
   golden file at A2 = 3/5**, not 5/5, until the command is fixed. (Score the
   substrate too — eval is not exempt from eval.)
2. **A4 counterfactual is the test of test discipline.** If you can't write a
   plausible scenario where A4 drops 2–3 points on the same code, you are not
   scoring — you are decorating.
3. **A retrospective B-only run is unmoored without an A run.** Five out of
   five looks suspicious because there's no contrast. Until we have a real
   single-agent A pass on the same task, B's score is observational, not
   comparative.

## The whole loop in one paragraph

Open the golden file → read its invariant + objective_check → run the check
(Part B) → for each subjective dim, find a specific mailbox/code line and
quote it (Part A) → write a counterfactual that would change the score →
count rounds + wall-time (Part C) → write it down here → if something hurt,
log it in `decision-log.md`. **That is one eval. Everything else is scale.**
