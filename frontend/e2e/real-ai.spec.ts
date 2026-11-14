// Real-provider smoke test (live Cohere Trial + local embeddings). Skipped unless E2E_REAL_AI=1:
//   $env:E2E_REAL_AI="1"; npx playwright test e2e/real-ai.spec.ts --project=desktop
// Uses about 3 Trial calls (insights + answer).
import { expect, test } from "@playwright/test";
import path from "node:path";

test.skip(!process.env.E2E_REAL_AI, "set E2E_REAL_AI=1 to run against real providers");

test("real Cohere answer with citation that opens the right PDF page", async ({ page }) => {
  test.setTimeout(240_000);
  await page.goto("/register");
  await page.getByLabel("Name").fill("Real AI");
  await page.getByLabel("Email").fill(`real-${Date.now().toString(36)}@example.com`);
  await page.getByLabel("Password").fill("correct-horse-9");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard/);

  await page.goto("/settings");
  await page.getByLabel(/Allow external AI processing/).check();
  await expect(page.getByText("Workspace AI setting updated")).toBeVisible();

  await page.goto("/upload");
  await expect(page.getByLabel("Choose files to upload")).toBeEnabled();
  await page.getByLabel("Choose files to upload").setInputFiles(path.join(__dirname, "fixtures", "report.pdf"));
  await page.getByRole("link", { name: "Open" }).click();
  await expect(page.getByText("Ready", { exact: true })).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText("Executive summary")).toBeVisible({ timeout: 90_000 });

  await page.goto("/assistant");
  await page.getByLabel("Your question").fill("How did operating margin and logistics costs change?");
  await page.getByRole("button", { name: "Send" }).click();
  const chip = page.getByRole("button", { name: "Open source 1" }).first();
  await expect(chip).toBeVisible({ timeout: 90_000 });
  console.log("ANSWER:", (await page.locator("p").filter({ hasText: /logistics/i }).first().innerText()).slice(0, 300));

  await chip.click();
  await expect(page.getByRole("dialog").getByText("Page 1")).toBeVisible();
  await page.getByRole("dialog").getByRole("link", { name: /Open in document/ }).click();
  await expect(page).toHaveURL(/\/view\?page=1/);
  await expect(page.locator(".textLayer span.dm-hl-cite").first()).toBeVisible({ timeout: 30_000 });
});
