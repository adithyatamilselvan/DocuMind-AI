import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

const run = Date.now().toString(36);

async function signUpAndUpload(page: Page, tag: string) {
  await page.goto("/register");
  await page.getByLabel("Name").fill("Insight Tester");
  await page.getByLabel("Email").fill(`e2e-ins-${run}-${tag}@example.com`);
  await page.getByLabel("Password").fill("correct-horse-9");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  await page.goto("/upload");
  await expect(page.getByLabel("Choose files to upload")).toBeEnabled();
  await page.getByLabel("Choose files to upload").setInputFiles(path.join(__dirname, "fixtures", "report.pdf"));
  await page.getByRole("link", { name: "Open" }).click();
  await expect(page.getByText("Ready", { exact: true })).toBeVisible({ timeout: 40_000 });
}

test("insights are generated after processing, link to evidence, and feed suggestions", async ({ page }, info) => {
  test.setTimeout(120_000);
  await signUpAndUpload(page, info.project.name);

  // 1. the insights panel fills in asynchronously
  await expect(page.getByRole("heading", { name: "AI insights" })).toBeVisible();
  await expect(page.getByText("Executive summary")).toBeVisible({ timeout: 40_000 });
  await expect(page.getByText("Key findings")).toBeVisible();
  await expect(page.getByText(/checked against the extracted text/)).toBeVisible();
  await expect(page.getByText("Structure")).toBeVisible();
  await expect(page.getByRole("link", { name: "Financial Results" })).toBeVisible();

  // 2. a finding's page link opens the viewer at that page with the quote highlighted
  await page.getByRole("link", { name: /Open page 1 in the viewer/ }).first().click();
  await expect(page).toHaveURL(/\/view\?page=1/);
  await expect(page.locator(".textLayer span.dm-hl-cite").first()).toBeVisible({ timeout: 30_000 });

  // 3. overview page lists the analysed document
  await page.goto("/insights");
  await expect(page.getByRole("heading", { name: "Document intelligence" })).toBeVisible();
  await expect(page.getByRole("link", { name: "report" })).toBeVisible();

  // 4. suggested questions come from real insights and start a grounded chat
  await page.goto("/assistant");
  const suggestion = page.getByLabel("Suggested questions").getByRole("button").first();
  await expect(suggestion).toBeVisible({ timeout: 15_000 });
  await suggestion.click();
  await expect(page).toHaveURL(/\/assistant\?c=/);
  await expect(page.getByRole("button", { name: "Open source 1" }).first()).toBeVisible({ timeout: 30_000 });
});
