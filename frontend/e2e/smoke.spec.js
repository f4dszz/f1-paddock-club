import { expect, test } from "@playwright/test";

test("mock/fallback planning flow supports selections, budget quote, debug trace, and honest links", async ({ page }) => {
  await page.goto("/?debug=1");

  await expect(page.getByText("PADDOCK CLUB")).toBeVisible();
  await page.getByTestId("gp-card-canadian-gp").click();

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

test("direct-only refinement removes connecting flights from transport card", async ({ page }) => {
  await page.goto("/?debug=1");
  await expect(page.getByText("PADDOCK CLUB")).toBeVisible();
  await page.getByTestId("gp-card-singapore-gp").click();
  await page.getByTestId("origin-input").fill("New York");
  await page.getByTestId("budget-input").fill("3000");
  await page.getByTestId("plan-submit").click();
  await expect(page.getByTestId("result-card-transport")).toBeVisible({ timeout: 120000 });

  await page.getByTestId("chat-input").fill("direct flights only please");
  await page.getByTestId("chat-send").click();
  // Refinement runs ReAct supervisor + reconciler; allow time for state commit + render.
  await page.waitForTimeout(8000);

  const transportText = (await page.getByTestId("result-card-transport").textContent()) ?? "";
  // No connecting flights should remain after a direct-only constraint is applied.
  expect(transportText).not.toMatch(/\b\d+\s*stop(s)?\b/i);
});

test("welcome form date inputs preserve values when filled in sequence", async ({ page }) => {
  await page.goto("/?debug=1");
  await expect(page.getByText("PADDOCK CLUB")).toBeVisible();
  await page.getByTestId("gp-card-canadian-gp").click();

  const depart = page.getByTestId("depart-date-input");
  const ret = page.getByTestId("return-date-input");
  // Two consecutive fills exercised the e.currentTarget.value-in-async-setter regression.
  await depart.fill("2026-05-22");
  await ret.fill("2026-05-26");
  await page.waitForTimeout(200);

  await expect(depart).toHaveValue("2026-05-22");
  await expect(ret).toHaveValue("2026-05-26");
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
  await page.waitForTimeout(8000);

  const tourText = (await page.getByTestId("result-card-tour").textContent()) ?? "";
  expect(tourText).toContain("National Gallery Singapore");
  // Bug pattern: replacement appended → `Gardens by the Bay with National Gallery Singapore` as one title.
  expect(tourText).not.toMatch(/Gardens by the Bay\s+with\s+National Gallery/i);
});
