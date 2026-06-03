import { expect, test } from "@playwright/test";

// Default no-key smoke E2E. Runs via `./scripts/e2e-local.sh` and the CI
// `e2e` job at `.github/workflows/ci.yml`. Both run with provider + LLM
// keys empty — these tests must not depend on the refinement supervisor
// firing (which requires a working LLM). Refinement-driven cases live in
// `refine.spec.js` and are env-gated by `E2E_INCLUDE_REFINE=1`.

// BS-12: never hardcode calendar dates — they rot into the past as races
// pass (this spec previously used 2026-05-22/26, both now past). Compute a
// near-future, strictly-ordered, <30-night depart/return pair relative to
// the run clock so the deterministic lane stays valid over time. Anchored
// to UTC midnight so the emitted ISO strings are stable regardless of TZ.
function futureTripDates(departOffsetDays = 90, nights = 4) {
  const DAY_MS = 24 * 60 * 60 * 1000;
  const toIso = (utcMs) => new Date(utcMs).toISOString().slice(0, 10);
  const now = new Date();
  const todayUtc = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  const depart = todayUtc + departOffsetDays * DAY_MS;
  return { depart: toIso(depart), ret: toIso(depart + nights * DAY_MS) };
}

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
  // BS-12: relative future dates, not hardcoded literals that rot into the past.
  const { depart: departIso, ret: returnIso } = futureTripDates();
  // Two consecutive fills exercised the e.currentTarget.value-in-async-setter regression.
  await depart.fill(departIso);
  await ret.fill(returnIso);

  // toHaveValue auto-polls up to expect.timeout (15s); no fixed sleep needed.
  await expect(depart).toHaveValue(departIso);
  await expect(ret).toHaveValue(returnIso);
});
