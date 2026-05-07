---
name: orchestrator
description: Use this skill whenever a user asks for substantive analysis, planning, or research that spans multiple parts of a codebase, multiple sources, or requires both verification AND synthesis. Trigger on requests like "review the architecture and plan...", "audit the codebase for...", "give me a roadmap for...", "fact-check then design...", or any task where a single naive read-and-write would miss things or hallucinate references. The skill partitions evidence gathering, synthesis, and verification. Use subagents only when the host environment and user/developer policy explicitly allow them; otherwise run the same workflow locally with narrow read scopes.
---

# Orchestrator: Parallel Fact-Check then Plan

A workflow for non-trivial analysis or planning tasks. The orchestrator (you, the parent agent) partitions the work into narrow fact-check streams, consolidation, and verification. If subagents are allowed by the current host and user/developer policy, dispatch them for the fact-check streams; otherwise do the same partitioned reads locally and keep each stream's notes separate. The output is a document grounded in real `file:line` references, not recollection.

## When to trigger

Use this skill when the user asks for any of:

- A **roadmap, plan, or design document** that needs to reflect what's actually in the codebase ("plan the migration from X to Y", "design the auth refactor", "give me a roadmap for adding i18n")
- An **audit or review** spanning multiple files, services, or domains ("audit the payment code", "review how we handle errors across the four services")
- **Comparative analysis** that needs accurate current state before recommending change ("should we keep Postgres or move to Mongo — fact-check first")
- Any task where the user explicitly says **"verify first"**, **"fact-check then ..."**, or warns against hallucinating references

Do NOT use for:

- Single-file changes or simple questions a one-shot read can answer
- Pure code execution tasks (run tests, format files) with no design component
- Conversational back-and-forth where the user hasn't asked for a deliverable yet
- Quick lookups ("what does function X do?") — just read the file

If you're unsure whether a task is heavy enough, ask the user one clarifying question about scope before deciding. Cheap to ask, expensive to over-engineer.

## The pattern

There are six steps. Each step has a reason — skip a step and you lose a specific guarantee.

### Step 1 — Pre-work clarification

Before launching any subagent, confirm scope with the user. Ask about:

- **Boundaries** — which directories, services, or domains are in scope; which are out
- **Depth** — overview vs. file-level plan vs. line-level prescription
- **Output format** — a single doc, a checklist, a decision matrix, slides
- **Audience** — the user themselves vs. a teammate vs. a PR reviewer
- **Constraints** — language (English / Chinese / bilingual), length, must-include sections

This step exists because subagent prompts are lossy. If you partition the codebase wrong or pick the wrong output format, you waste an entire parallel fan-out. Five minutes of clarification saves an hour of rework.

Use `AskUserQuestion` (or equivalent) for the structured questions. If only one thing is unclear, a normal follow-up message is fine.

### Step 2 — Build a TodoList

Maintain a visible task list with one entry per fact-check workstream, plus one consolidation entry, plus one verification entry. Example shape:

- Fact-check: data layer (workstream A)
- Fact-check: API layer (workstream B)
- Fact-check: frontend integration (workstream C)
- Consolidate findings into roadmap doc
- Spot-check the doc against the codebase
- Executive summary in chat

This step exists for two reasons: it forces you to partition workstreams BEFORE dispatching (catches overlap), and it gives the user a progress signal during the long parallel phase.

### Step 3 — Fact-checking workstreams

Create N workstreams (typically 2–5; rarely more than 6). When subagents are explicitly permitted, spawn them in parallel. When they are not permitted, execute the workstreams locally one by one or with ordinary file reads, preserving the same boundaries. Each workstream has:

- A **narrow file or directory partition** — non-overlapping with other agents
- A **specific list of claims to verify** — phrased as questions ("Does `foo.py` actually import bar?") not vague topics
- **Required structured headings** in the report — e.g. `Status today (verified)`, `Files involved`, `Hidden coupling`, `Risks`
- A **citation requirement** — every claim must cite `path/to/file.py:line` or be marked `[unverified]`
- A **word limit** — usually 600–1200 words per subagent. Without a limit, agents over-explain.

This step exists to keep the orchestrator's context small. With subagents, the orchestrator reads only structured reports. Without subagents, the orchestrator still limits context by reading only the files in the active workstream and writing concise notes before moving on.

Critical: **partition the codebase, don't replicate it**. If two agents read overlapping files, you get duplicated work and conflicting summaries. When two areas are genuinely entangled, merge them into one larger workstream rather than splitting and hoping.

See `references/subagent-prompt-templates.md` for the Explore-fact-check template.

### Step 4 — Consolidation

Once all fact-check workstreams are complete, consolidate the verified notes. If subagents are explicitly permitted, this may be a single `Plan`-style or general-purpose subagent; otherwise do the synthesis locally. Feed the consolidator:

- The **verified findings** from Step 3, pasted in full as ground truth
- An **explicit output template** — section headings, bullet structure, table columns, length target
- A **directive to NOT re-verify** — the consolidator's job is synthesis, not re-reading. Re-reading wastes context and risks re-hallucinating references the fact-checkers already pinned down.
- The **target audience and tone** from Step 1

The output is the deliverable's first draft. It should be structurally complete: every section filled, every recommendation tied to a verified fact from Step 3.

This step exists because synthesis is a different skill from verification. The same agent that just spent its context reading 30 files is bad at stepping back and writing a clean structured doc. Splitting the role gives both halves room to do their job.

See the Plan-consolidator template in `references/subagent-prompt-templates.md`.

### Step 5 — Independent verification

Verify 5 to 10 specific claims from the consolidated output. If subagents are explicitly permitted, use a fresh `Explore`-style subagent different from any used in Step 3; otherwise verify locally with direct file reads and searches. For each claim:

- Provide the **exact quote and location** in the doc
- Ask for **PASS / FAIL / PARTIAL** with quoted evidence from the codebase
- Flag any **fabricated `file:line` references** explicitly

Do NOT ask the verifier to re-do the whole analysis. The point is spot-checking, not duplication. Pick the claims that would be most embarrassing if wrong: line numbers, function names, "X depends on Y" claims, "the codebase doesn't have Z" negative claims.

This step exists because LLM consolidators occasionally invent plausible-sounding references when synthesizing. A 10-claim spot-check catches almost all of these without re-running the whole pipeline.

If the verifier finds failures, you have two options: (a) patch the doc with corrections inline, or (b) ask the consolidator to revise. Patching is faster for ≤3 errors; revision is cleaner for systemic problems.

See the Verifier template in `references/subagent-prompt-templates.md`.

### Step 6 — Executive summary

In chat, write 5–15 lines:

- One line: what was produced and where it lives
- 3–6 bullets: the most important findings or recommendations
- One line: known caveats or follow-ups
- Link to the full doc

Do NOT re-narrate the doc — the user can open it. The summary's job is to let the user decide whether to read further or act immediately.

## Designing subagent prompts

Three properties make a subagent prompt good:

1. **Narrow** — a single agent should be able to hold the entire scope in its head. If you find yourself writing "and also...", split into two agents.
2. **Concrete claims, not vague topics** — "Verify that `state.py` defines a `currency` field and where it's read" beats "Look at the state schema". Concrete claims are checkable.
3. **Structured output** — give exact section headings the agent must use. Free-form output from N agents is impossible to merge cleanly in Step 4.

A good fact-check prompt is roughly:

> Read these files: `[explicit list]`. Verify these claims: `[numbered list, 3–8 items]`. Report under these headings: `Status today (verified)`, `Files involved`, `Hidden coupling`, `Open questions`. Every claim must cite `file:line` or be marked `[unverified]`. Limit: 800 words.

If you need broader exploration ("find all places that touch authentication"), do a single discovery agent first, then split into narrow agents using its output. Don't let one agent both discover and verify — those are different tasks.

## Failure modes

**Too many agents.** Beyond 5–6 parallel fact-checkers, the orchestrator spends more context merging reports than the parallelism saves. Fewer, larger workstreams are usually better.

**Overlapping scope.** Two agents reading the same files produce two slightly different summaries that you then have to reconcile. Always check partitioning in Step 2 before dispatching.

**No verification step.** Skipping Step 5 ships hallucinated references. The consolidator will sometimes invent a `file.py:123` that looks right but doesn't exist. A 10-minute spot-check is the cheapest insurance you can buy.

**Vague subagent prompts.** "Look at the auth code and report findings" produces unstructured prose that's hard to consolidate. Always specify section headings and concrete claims.

**Re-verification in Step 4.** If the consolidator re-reads files, you've wasted Step 3 and the consolidator's context shrinks for the synthesis it's supposed to do. The prompt must explicitly say: trust the verified findings, do not re-read.

**Skipping clarification.** Diving into Step 3 with the wrong scope or output format wastes the entire fan-out. Clarify first.

## Examples

### Example 1: Migration roadmap

User says: *"Plan our migration from Stripe to Adyen — verify what we actually have first."*

- **Step 1**: Ask whether scope includes webhooks, refunds, subscriptions, or only checkout; ask whether output should be file-level or service-level.
- **Step 3**: Three parallel agents — one on `payments/` directory, one on webhook handlers across services, one on the frontend payment form.
- **Step 4**: Consolidator produces a doc with sections "Current state", "Migration phases", "Per-file changes", "Risk register".
- **Step 5**: Verifier spot-checks 8 claims — e.g. "Stripe SDK is imported in 12 files" (count it), "no Adyen code exists today" (negative claim, search confirms), four specific `file:line` references.
- **Step 6**: 8-line summary: scope, three migration phases, biggest risk (webhook signature verification), link to doc.

### Example 2: Architecture review

User says: *"Audit our error handling across the four backend services and tell me what's inconsistent."*

- **Step 1**: Confirm "inconsistent" means surface format vs. retry policy vs. logging — pick one or all three.
- **Step 3**: Four parallel agents, one per service. Same structured headings each: `Surface format`, `Retry policy`, `Logging convention`, `Exceptions caught vs. propagated`.
- **Step 4**: Consolidator produces a comparison matrix (services as columns, dimensions as rows) plus a recommendations section.
- **Step 5**: Verifier checks the matrix cells — pick 8 cells across the matrix and confirm them in code.
- **Step 6**: Summary lists the three biggest divergences and the recommended convergence target.

These examples are just shapes. Adapt the partitioning to the actual codebase — there's no fixed N or fixed section list.
