import { expect, test, type Page } from "@playwright/test";

const run = Date.now().toString(36);

async function signUp(page: Page, tag: string) {
  await page.goto("/register");
  await page.getByLabel("Name").fill("Upload Tester");
  await page.getByLabel("Email").fill(`e2e-up-${run}-${tag}@example.com`);
  await page.getByLabel("Password").fill("correct-horse-9");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
}

test("upload is gated by AI consent, validates files, detects duplicates and downloads", async ({ page }, info) => {
  await signUp(page, info.project.name);

  await page.goto("/upload");
  await expect(page.getByText("External AI processing is not enabled for this workspace")).toBeVisible();
  await expect(page.getByLabel("Choose files to upload")).toBeDisabled();

  // Admin grants consent in Settings.
  await page.goto("/settings");
  await page.getByLabel(/Allow external AI processing/).check();
  await expect(page.getByText("Workspace AI setting updated")).toBeVisible();

  await page.goto("/upload");
  const input = page.getByLabel("Choose files to upload");
  await expect(input).toBeEnabled();

  // Client-side rejection of an unsupported type.
  await input.setInputFiles({ name: "malware.exe", mimeType: "application/octet-stream", buffer: Buffer.from("MZ") });
  await expect(page.getByText("Only PDF, DOCX and TXT files are supported")).toBeVisible();

  // Real upload through the proxy to the API.
  const content = `E2E document ${run} ${info.project.name}\nSome text for the pipeline.\n`;
  await input.setInputFiles({ name: "e2e-notes.txt", mimeType: "text/plain", buffer: Buffer.from(content) });
  await expect(page.getByText(/uploaded, processing will continue/)).toBeVisible();

  // Same bytes again -> duplicate detection.
  await input.setInputFiles({ name: "renamed.txt", mimeType: "text/plain", buffer: Buffer.from(content) });
  await expect(page.getByText(/Identical to existing document/)).toBeVisible();

  // Appears in the library and the original file can be downloaded unchanged.
  await page.goto("/documents");
  await page.getByRole("link", { name: "e2e-notes" }).click();
  await expect(page.getByRole("heading", { name: "e2e-notes" })).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "Download" }).first().click(),
  ]);
  expect(download.suggestedFilename()).toBe("e2e-notes.txt");
});
