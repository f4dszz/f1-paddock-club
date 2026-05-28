import { expect, test } from "@playwright/test";

// Save → list → load round-trip via the SavedTrips panel.
// Gated by E2E_INCLUDE_SAVED=1; runs in the deterministic lane.

test("save current plan, reload page, load it back from My Trips", async ({ page }) => {
  await page.goto("/?debug=1");
  await expect(page.getByText("PADDOCK CLUB")).toBeVisible();
  await page.getByTestId("gp-card-italian-gp").click();

  await page.getByTestId("origin-input").fill("New York");
  await page.getByTestId("budget-input").fill("2800");
  await page.getByTestId("plan-submit").click();

  await expect(page.getByTestId("result-card-ticket")).toBeVisible({ timeout: 120000 });

  // Save the trip
  await page.getByTestId("save-trip-btn").click();
  await expect(page.getByTestId("save-trip-btn")).toContainText(/SAVED/, { timeout: 5000 });

  // Reload the page — saved trip must survive in Postgres / SQLite.
  await page.reload();
  await expect(page.getByText("PADDOCK CLUB")).toBeVisible();
  await page.getByTestId("gp-card-italian-gp").click();

  // Open My Trips
  await page.getByTestId("my-trips-btn").click();
  await expect(page.getByTestId("saved-trips-panel")).toBeVisible();

  // At least one saved trip item should appear; click Load on the first.
  const item = page.getByTestId("saved-trip-item").first();
  await expect(item).toBeVisible({ timeout: 10000 });
  await item.getByTestId("saved-trip-load").click();

  // After load, results should be restored.
  await expect(page.getByTestId("result-card-ticket")).toBeVisible({ timeout: 10000 });
});
