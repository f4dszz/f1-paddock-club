import { expect, test } from "@playwright/test";

// Default no-key smoke E2E. Runs via `./scripts/e2e-local.sh` and the CI
// `e2e` job at `.github/workflows/ci.yml`. Both run with provider + LLM
// keys empty — these tests must not depend on the refinement supervisor
// firing (which requires a working LLM). Refinement-driven cases live in
// `refine.spec.js` and are env-gated by `E2E_INCLUDE_REFINE=1`.

test("mock/fallback planning flow supports selections, budget quote, debug trace, and honest links", async ({ page }) => {
  await page.goto("/?debug=1");

  await expect(page.getByText("PADDOCK CLUB")).toBeVisible();
  await page.getByTestId("gp-card-italian-gp").click();

  await page.getByTestId("origin-input").fill("New York");
  await page.getByTestId("budget-input").fill("2800");
  await page.getByTestId("special-requests-input").fill("vegetarian meals and easy Sunday transit");
  await page.getByTestId("plan-submit").click();

  await expect(page.getByTestId("result-card-ticket")).toBeVisible({ timeout: 120000 });
  await expect(page.getByTestId("result-card-transport")).toBeVisible();
  await expect(page.getByTestId("result-card-hotel")).toBeVisible();
  await expect(page.getByTestId("budget-panel")).toContainText("Baseline estimate");
  await expect(page.getByTestId("debug-trace")).toContainText("trace.budget_final");

  for (const zone of ["ticket", "transport", "hotel"]) {
    const item = page.getByTestId(`result-item-${zone}-0`);
    await item.scrollIntoViewIfNeeded();
    await item.click();
  }

  await expect(page.getByTestId("budget-panel")).toContainText("Your selected total");
  await expect(page.getByTestId("book-button-ticket")).toContainText(/Open /);
  await expect(page.getByTestId("book-button-ticket")).not.toContainText("Book");
  await expect(page.getByTestId("book-button-transport")).toContainText(/Open /);
  await expect(page.getByText("not a purchase confirmation").first()).toBeVisible();
});

test("welcome form date inputs preserve values when filled in sequence", async ({ page }) => {
  await page.goto("/?debug=1");
  await expect(page.getByText("PADDOCK CLUB")).toBeVisible();
  await page.getByTestId("gp-card-italian-gp").click();

  const depart = page.getByTestId("depart-date-input");
  const ret = page.getByTestId("return-date-input");
  // Two consecutive fills exercised the e.currentTarget.value-in-async-setter regression.
  await depart.fill("2026-05-22");
  await ret.fill("2026-05-26");

  // toHaveValue auto-polls up to expect.timeout (15s); no fixed sleep needed.
  await expect(depart).toHaveValue("2026-05-22");
  await expect(ret).toHaveValue("2026-05-26");
});
