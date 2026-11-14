import { expect, test, type Browser, type Page } from "@playwright/test";
import path from "node:path";

const run = Date.now().toString(36);

async function newUser(browser: Browser, tag: string): Promise<Page> {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto("/register");
  await page.getByLabel("Name").fill(`User ${tag}`);
  await page.getByLabel("Email").fill(`e2e-iso-${run}-${tag}@example.com`);
  await page.getByLabel("Password").fill("correct-horse-9");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  return page;
}

test("another workspace cannot see a document; deleted content is no longer retrievable", async ({ browser }, info) => {
  test.setTimeout(150_000);
  const a = await newUser(browser, `a-${info.project.name}`);
  const b = await newUser(browser, `b-${info.project.name}`);

  await a.goto("/upload");
  await expect(a.getByLabel("Choose files to upload")).toBeEnabled();
  await a.getByLabel("Choose files to upload").setInputFiles(path.join(__dirname, "fixtures", "report.pdf"));
  await a.getByRole("link", { name: "Open" }).click();
  await expect(a.getByText("Ready", { exact: true })).toBeVisible({ timeout: 40_000 });
  const docUrl = a.url();

  // B (different workspace) gets a not-found for A's document and finds nothing by search
  await b.goto(docUrl);
  await expect(b.locator("div[role=alert]").first()).toContainText(/not found/i);
  await b.goto("/search");
  await b.getByLabel("Search query").fill("logistics");
  await b.getByLabel("Search mode").selectOption("keyword");
  await b.getByRole("button", { name: "Search" }).click();
  await expect(b.getByText("No matching passages")).toBeVisible();

  // A can find it, then deletes it and it disappears from search and answers
  await a.goto("/search");
  await a.getByLabel("Search query").fill("logistics");
  await a.getByLabel("Search mode").selectOption("keyword");
  await a.getByRole("button", { name: "Search" }).click();
  await expect(a.getByText(/logistics costs fell/).first()).toBeVisible();

  await a.goto(docUrl);
  await a.getByRole("button", { name: "Delete", exact: true }).first().click();
  await a.getByRole("button", { name: "Delete", exact: true }).last().click();
  await expect(a).toHaveURL(/\/documents$/);

  await a.goto("/search");
  await a.getByLabel("Search query").fill("logistics");
  await a.getByLabel("Search mode").selectOption("keyword");
  await a.getByRole("button", { name: "Search" }).click();
  await expect(a.getByText("No matching passages")).toBeVisible();
  await a.goto("/assistant");
  await a.getByLabel("Your question").fill("How did operating margin and logistics costs change?");
  await a.getByRole("button", { name: "Send" }).click();
  await expect(a.getByText(/couldn't find enough evidence/)).toBeVisible({ timeout: 30_000 });
});

test("core pages do not overflow horizontally", async ({ page }, info) => {
  await page.goto("/register");
  await page.getByLabel("Name").fill("Overflow");
  await page.getByLabel("Email").fill(`e2e-ovf-${run}-${info.project.name}@example.com`);
  await page.getByLabel("Password").fill("correct-horse-9");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  for (const p of ["/dashboard", "/documents", "/upload", "/assistant", "/insights", "/search", "/knowledge-bases", "/analysis", "/reports", "/workspace", "/settings", "/activity"]) {
    await page.goto(p);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    expect(overflow, `${p} overflows horizontally`).toBe(false);
  }
});
