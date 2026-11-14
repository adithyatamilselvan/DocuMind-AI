import { expect, test } from "@playwright/test";
import fs from "node:fs";

const run = Date.now().toString(36);
const A = "# Sleep and Memory\n\nThe aim of this study is to investigate whether sleep deprivation reduces memory consolidation. We conducted a randomized experiment with n = 120 participants over four weeks. The results show that recall accuracy decreased by twenty percent after sleep deprivation. We conclude that sleep is essential for memory consolidation. A limitation of this work is that all participants were students.";
const B = "# Napping Study\n\nThe objective of this survey is to measure the effect of napping on learning. We surveyed 300 respondents about their study habits. The results show that recall accuracy increased by five percent after short naps. We conclude that napping has a small positive effect. This study is limited by self reported data.";

test("literature review, comparison and report export through the real stack", async ({ page }, info) => {
  test.setTimeout(150_000);
  await page.goto("/register");
  await page.getByLabel("Name").fill("Research Tester");
  await page.getByLabel("Email").fill(`e2e-res-${run}-${info.project.name}@example.com`);
  await page.getByLabel("Password").fill("correct-horse-9");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard/);

  await page.goto("/upload");
  const input = page.getByLabel("Choose files to upload");
  await expect(input).toBeEnabled();
  await input.setInputFiles([
    { name: "sleep.txt", mimeType: "text/plain", buffer: Buffer.from(A) },
    { name: "naps.txt", mimeType: "text/plain", buffer: Buffer.from(B) },
  ]);
  await expect(page.getByText(/uploaded, processing will continue/)).toHaveCount(2, { timeout: 30_000 });

  await page.goto("/analysis");
  await expect(page.getByLabel("sleep", { exact: true })).toBeVisible({ timeout: 40_000 });
  await page.getByLabel("sleep", { exact: true }).check();
  await page.getByLabel("naps", { exact: true }).check();
  await page.getByRole("button", { name: "Literature review" }).click();
  const review = page.getByRole("listitem").filter({ hasText: "Literature review (2 papers)" });
  await expect(review.getByText("completed")).toBeVisible({ timeout: 60_000 });

  await page.getByRole("button", { name: "Compare documents" }).click();
  const cmp = page.getByRole("listitem").filter({ hasText: "sleep vs naps" });
  await expect(cmp.getByText("completed")).toBeVisible({ timeout: 60_000 });

  // report from the literature review
  await review.getByRole("button", { name: "Report" }).click();
  await expect(page).toHaveURL(/\/reports\/.+/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "Comparison of papers" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("heading", { name: /AI-identified/ })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Methodology" })).toBeVisible();

  for (const fmt of ["PDF", "DOCX"] as const) {
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("link", { name: fmt }).click(),
    ]);
    expect(download.suggestedFilename().toLowerCase()).toContain(fmt.toLowerCase());
    expect(fs.statSync((await download.path())!).size).toBeGreaterThan(1000);
  }

  await page.goto("/reports");
  await expect(page.getByRole("link", { name: /Literature review/ })).toBeVisible();
});
