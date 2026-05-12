import { expect, test } from "@playwright/test";

// Refinement E2E. Gated by E2E_INCLUDE_REFINE=1.
//
// The deterministic test contract uses `LLM_STUB_MODE=1` against the backend
// (`scripts/e2e-local.sh` passes that env through when set). That switches
// `backend/refine.py` to a test-only stub that directly invokes the
// server-side mutation helpers (`_apply_constraint_filters`,
// `apply_line_update`) without any real LLM call. The stub is gated by
// `APP_ENV=test` + `LLM_STUB_MODE=1`, so production keeps the honest
// "LLM not configured" early return when keys are absent.
//
// Run locally with:
//   E2E_INCLUDE_REFINE=1 LLM_STUB_MODE=1 ./scripts/e2e-local.sh
//
// This is the deterministic test contract. `scripts/e2e-local.sh` clears
// real provider + LLM keys before starting the backend, so the spec does
// not run against a real LLM through that script. Driving these tests
// with a real LLM would require a separate manual backend bringup with
// `OPENAI_API_KEY` set plus `LLM_STUB_MODE=1` left unset, and the result
// would be non-deterministic — not the path documented here.
//
// `playwright.config.js` ignores this file unless `E2E_INCLUDE_REFINE=1`.

test("direct-only refinement: connecting flight is filtered after chat", async ({ page }) => {
  await page.goto("/?debug=1");
  await expect(page.getByText("PADDOCK CLUB")).toBeVisible();
  await page.getByTestId("gp-card-singapore-gp").click();
  await page.getByTestId("origin-input").fill("New York");
  await page.getByTestId("budget-input").fill("3000");
  await page.getByTestId("plan-submit").click();
  await expect(page.getByTestId("result-card-transport")).toBeVisible({ timeout: 120000 });

  // BEFORE: the LLM_STUB_MODE=1 transport mock adds a connecting flight
  // alongside the direct option, so the transport card must render a stops
  // indicator at baseline. Failing here means the test env is not actually
  // in stub mode (LLM_STUB_MODE not set or backend did not pick it up).
  //
  // Note: the rendered text concatenates summary + detail without a space
  // ("Singapore1 stop via Dubai"), so the digit-before-stop pattern must
  // not anchor on a `\b` before the digit. `\s+` between digit and "stop"
  // is what we actually need.
  await expect(page.getByTestId("result-card-transport"))
    .toContainText(/\d+\s+stop(s)?/i, { timeout: 120000 });

  // Trigger refinement: the stub branch in backend/refine.py sets
  // active_constraints.direct_only=True and runs _apply_constraint_filters,
  // which removes the connecting flight from state.transport.
  await page.getByTestId("chat-input").fill("direct flights only please");
  await page.getByTestId("chat-send").click();

  // AFTER: connecting flight removed; the card no longer renders any stops
  // indicator. Real positive assertion — passes only if the deterministic
  // refinement stub actually mutated state.transport server-side.
  await expect
    .poll(
      async () => (await page.getByTestId("result-card-transport").textContent()) ?? "",
      { timeout: 60000, intervals: [500, 1000, 2000] },
    )
    .not.toMatch(/\d+\s+stop(s)?/i);
});

test("english tour replacement: tour card title is rewritten by stub", async ({ page }) => {
  await page.goto("/?debug=1");
  await expect(page.getByText("PADDOCK CLUB")).toBeVisible();
  await page.getByTestId("gp-card-singapore-gp").click();
  await page.getByTestId("origin-input").fill("New York");
  await page.getByTestId("budget-input").fill("3000");
  await page.getByTestId("plan-submit").click();
  await expect(page.getByTestId("result-card-tour")).toBeVisible({ timeout: 120000 });

  // BEFORE: the GP-aware tour mock returns Singapore tours including
  // "Gardens by the Bay" at baseline. Failing here means tour.py mock is
  // not returning the expected Singapore list (regression on the
  // _TOUR_MOCK_BY_GP lookup).
  await expect(page.getByTestId("result-card-tour"))
    .toContainText("Gardens by the Bay", { timeout: 120000 });

  // Trigger refinement: the stub branch in backend/refine.py matches the
  // "Replace X with Y" pattern via replacement_target_name/replacement_name
  // and calls apply_line_update on state.tour.
  await page.getByTestId("chat-input").fill("Replace Gardens by the Bay with National Gallery Singapore");
  await page.getByTestId("chat-send").click();

  // AFTER: stub-rewritten tour line is rendered. Real positive assertion.
  await expect(page.getByTestId("result-card-tour")).toContainText(
    "National Gallery Singapore",
    { timeout: 60000 },
  );

  const tourText = (await page.getByTestId("result-card-tour").textContent()) ?? "";
  // Bug-pattern guard: the original bug was the new title being concatenated
  // onto the OLD title in the title position, e.g. "Gardens by the Bay with
  // National Gallery Singapore — ...". The current correct output places the
  // new title in the title position and may legitimately mention the old
  // name in the trailing "Requested update: ..." suffix appended by
  // `apply_line_update`. So we only check the title segment (the chars
  // before the first " — " em-dash separator) — the new title must appear
  // there and the old title must not.
  const firstSeparator = tourText.indexOf(" — ");
  const titlePortion = firstSeparator >= 0 ? tourText.slice(0, firstSeparator) : tourText;
  expect(titlePortion).toContain("National Gallery Singapore");
  expect(titlePortion).not.toMatch(/Gardens by the Bay/i);
});
