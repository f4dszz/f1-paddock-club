import { expect, test } from "@playwright/test";

// Explainability ("Why this card?") coverage. Runs in the default no-key
// lane — rationales are built deterministically at planning time by
// backend/tools/_rationale.py and attached to every ticket / flight /
// hotel item (see backend/agents/tickets.py:51 et al.). No LLM call is
// involved, so the test does not need LLM_STUB_MODE.
//
// The reviewer R9 non-negotiable: this spec must exercise the actual
// "i" card affordance (not synthetically render a panel), and must
// assert the rationale + data-source-path content visibly renders, not
// merely that the panel opens.

test("opening the ticket explain panel renders rationale reasons and data source path", async ({ page }) => {
  await page.goto("/?debug=1");
  await expect(page.getByText("PADDOCK CLUB")).toBeVisible();
  await page.getByTestId("gp-card-italian-gp").click();
  await page.getByTestId("origin-input").fill("New York");
  await page.getByTestId("budget-input").fill("2800");
  await page.getByTestId("plan-submit").click();

  await expect(page.getByTestId("result-card-ticket")).toBeVisible({ timeout: 120000 });

  // BEFORE: no explain panel visible. The dialog only mounts when the
  // user clicks the "i" affordance.
  await expect(page.getByTestId("explain-panel")).toBeHidden();

  // Click the "i" affordance on the VIP grandstand ticket (index 2 of
  // the mock). build_ticket_rationale (backend/tools/_rationale.py:384)
  // attaches a rationale with stable reason strings for VIP tag.
  const explainButton = page.getByTestId("explain-button-ticket-2");
  await explainButton.scrollIntoViewIfNeeded();
  await explainButton.click();

  // AFTER: the panel mounts. Assert structural sections render.
  const panel = page.getByTestId("explain-panel");
  await expect(panel).toBeVisible();

  // Rationale content — the VIP-tagged ticket's deterministic reasons.
  const reasons = page.getByTestId("explain-reasons");
  await expect(reasons).toBeVisible();
  await expect(reasons).toContainText("Tag: VIP");
  // Reason includes the section field from the mock ticket.
  await expect(reasons).toContainText("Pit lane + podium");

  // Data source path — the mock ticket source resolves to the configured
  // firecrawl → llm_estimate → mock fallback chain (see
  // backend/tools/_rationale.py:_TICKET_SOURCE_CHAIN). The frontend
  // renders these as labeled source badges; "Mock data" is the
  // sourceLabel for the terminal "mock" entry.
  const sourcePath = page.getByTestId("explain-source-path");
  await expect(sourcePath).toBeVisible();
  await expect(sourcePath).toContainText("Mock data");

  // Closing the panel via the close button unmounts it.
  await panel.getByRole("button", { name: "Close" }).click();
  await expect(page.getByTestId("explain-panel")).toBeHidden();
});
