import { expect, test } from "@playwright/test";

// LLM-gated refinement E2E. Only runs when E2E_INCLUDE_REFINE=1.
//
// Why this is a separate spec:
// `scripts/e2e-local.sh` and CI both run with provider + LLM keys empty,
// which causes `backend/refine.py` to return early and the refinement
// supervisor never fires. Refinement assertions in that environment would
// be trivially true regardless of whether refinement actually happened, so
// these cases live outside the default no-key smoke lane until a
// deterministic refinement path exists.
//
// To run locally with a configured LLM:
//   E2E_INCLUDE_REFINE=1 OPENAI_API_KEY=sk-... npm run e2e
//
// `playwright.config.js` ignores this file unless `E2E_INCLUDE_REFINE=1`.

test("direct-only refinement: chat path completes; transport card lacks stops indicator", async ({ page }) => {
  await page.goto("/?debug=1");
  await expect(page.getByText("PADDOCK CLUB")).toBeVisible();
  await page.getByTestId("gp-card-singapore-gp").click();
  await page.getByTestId("origin-input").fill("New York");
  await page.getByTestId("budget-input").fill("3000");
  await page.getByTestId("plan-submit").click();
  await expect(page.getByTestId("result-card-transport")).toBeVisible({ timeout: 120000 });

  await page.getByTestId("chat-input").fill("direct flights only please");
  await page.getByTestId("chat-send").click();

  // NOTE: structural smoke only, not a strict constraint-enforcement test.
  // The no-key fallback transport card is already a single direct round trip
  // with no `stop` indicator, so this assertion can pass without proving the
  // supervisor + reconciler actually applied the constraint. This test
  // confirms the refinement chat path completes and the transport card is
  // not broken; strengthening to require a positive signal (visible
  // `Direct flights only` constraint chip plus non-error reply, or a
  // fixture-driven before-state that has stops to remove) is future work
  // tracked alongside the S2 fixture lane.
  await expect
    .poll(
      async () => (await page.getByTestId("result-card-transport").textContent()) ?? "",
      { timeout: 60000, intervals: [500, 1000, 2000] },
    )
    .not.toMatch(/\b\d+\s*stop(s)?\b/i);
});

test("english tour replacement does not append the old title", async ({ page }) => {
  await page.goto("/?debug=1");
  await expect(page.getByText("PADDOCK CLUB")).toBeVisible();
  await page.getByTestId("gp-card-singapore-gp").click();
  await page.getByTestId("origin-input").fill("New York");
  await page.getByTestId("budget-input").fill("3000");
  await page.getByTestId("plan-submit").click();
  await expect(page.getByTestId("result-card-tour")).toBeVisible({ timeout: 120000 });

  // Use the canonical Singapore mock tour reference from docs/current.md.
  await page.getByTestId("chat-input").fill("Replace Gardens by the Bay with National Gallery Singapore");
  await page.getByTestId("chat-send").click();

  // Wait for the tour card to render the replacement title (auto-polling).
  await expect(page.getByTestId("result-card-tour")).toContainText(
    "National Gallery Singapore",
    { timeout: 60000 },
  );

  const tourText = (await page.getByTestId("result-card-tour").textContent()) ?? "";
  // Bug pattern: replacement appended → `Gardens by the Bay with National Gallery Singapore` as one title.
  expect(tourText).not.toMatch(/Gardens by the Bay\s+with\s+National Gallery/i);
});
