import { expect, test, type Page } from "@playwright/test";

const run = Date.now().toString(36);

async function signUp(page: Page, tag: string) {
  await page.goto("/register");
  await page.getByLabel("Name").fill("Lib Tester");
  await page.getByLabel("Email").fill(`e2e-lib-${run}-${tag}@example.com`);
  await page.getByLabel("Password").fill("correct-horse-9");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
}

test("dashboard shows real (zero) metrics for a new workspace", async ({ page }, info) => {
  await signUp(page, `dash-${info.project.name}`);
  await expect(page.getByText("AI requests (30d)")).toBeVisible();
  await expect(page.getByText("No AI usage recorded yet.")).toBeVisible();
  await expect(page.getByText("Documents you open will show up here.")).toBeVisible();
  // the activity feed is derived from the audit log; registration is recorded in the new workspace
  await expect(page.getByText("created their account")).toBeVisible();
});

test("document library empty state, filters and navigation", async ({ page }, info) => {
  await signUp(page, `lib-${info.project.name}`);
  await page.goto("/documents");
  await expect(page.getByRole("heading", { name: "Documents" })).toBeVisible();
  await expect(page.getByText("No documents yet")).toBeVisible();

  await page.getByLabel("Search documents").fill("nothing");
  await expect(page.getByText("No documents match your filters")).toBeVisible();

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);
});

test("unknown document id shows an error state", async ({ page }, info) => {
  await signUp(page, `404-${info.project.name}`);
  await page.goto("/documents/64b7f0f0f0f0f0f0f0f0f0f0");
  await expect(page.locator("div[role=alert]").first()).toContainText(/not found/i);
});
