import { expect, test } from "@playwright/test";

// Unpriced / incomplete quote coverage. Gated by E2E_INCLUDE_REFINE=1.
//
// The deterministic test contract requires LLM_STUB_MODE=1 against the
// backend: that env enables an extra "Paddock Club (price on request)"
// ticket with price=0 in backend/agents/tickets.py:_ticket_mock. Selecting
// that ticket forces backend/tools/recompute.py to emit
// `quote_complete=false` with "Tickets" in `missing_price_categories`.
// The frontend BudgetPanel then renders the amber "Incomplete quote"
// pending-price tone (frontend/components/BudgetPanel.jsx:39).
//
// Run locally with:
//   E2E_INCLUDE_REFINE=1 LLM_STUB_MODE=1 ./scripts/e2e-local.sh
//
// `playwright.config.js` ignores this file unless `E2E_INCLUDE_REFINE=1`.

test("selecting the unpriced ticket option renders the incomplete-quote amber path with debug metadata", async ({ page }) => {
  await page.goto("/?debug=1");
  await expect(page.getByText("PADDOCK CLUB")).toBeVisible();
  await page.getByTestId("gp-card-italian-gp").click();
  await page.getByTestId("origin-input").fill("New York");
  await page.getByTestId("budget-input").fill("2800");
  await page.getByTestId("plan-submit").click();

  await expect(page.getByTestId("result-card-ticket")).toBeVisible({ timeout: 120000 });

  // BEFORE: baseline budget is `quote_complete=true`. The amber/pending
  // status text from BudgetPanel:39 must be absent on the baseline run.
  await expect(page.getByTestId("budget-panel")).toContainText("Baseline estimate");
  await expect(page.getByTestId("budget-panel")).not.toContainText("Incomplete quote");

  // The unpriced item is appended at the end of the ticket mock — index 3
  // (the three priced VALUE/PICK/VIP entries come first). It renders with
  // "Price not provided" via transformResults.js when pv === 0.
  const unpricedRow = page.getByTestId("result-item-ticket-3");
  await unpricedRow.scrollIntoViewIfNeeded();
  await expect(unpricedRow).toContainText("Paddock Club");
  await expect(unpricedRow).toContainText("Price not provided");

  await unpricedRow.click();

  // AFTER: BudgetPanel must switch to the "selected total" basis with the
  // amber incomplete-quote line citing the missing "Tickets" price
  // category. This is the real positive assertion: backend recompute saw
  // a selected item with price=0 and set quote_complete=false.
  await expect(page.getByTestId("budget-panel")).toContainText("Your selected total", { timeout: 30000 });
  await expect(page.getByTestId("budget-panel")).toContainText("Incomplete quote");
  await expect(page.getByTestId("budget-panel")).toContainText("Tickets");

  // Debug trace metadata must also reflect the incomplete quote. The debug
  // log records ws.message events; the latest "trace.budget_final" payload
  // includes the budget_summary which itself carries quote_complete=false
  // and missing_price_categories. We assert on the rendered debug pane.
  const debugTrace = page.getByTestId("debug-trace");
  await expect(debugTrace).toContainText("trace.budget_final", { timeout: 30000 });
  await expect(debugTrace).toContainText('"quote_complete":false');
  await expect(debugTrace).toContainText("Tickets");
});
