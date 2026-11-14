import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

const run = Date.now().toString(36);

async function signUp(page: Page, tag: string) {
  await page.goto("/register");
  await page.getByLabel("Name").fill("Chat Tester");
  await page.getByLabel("Email").fill(`e2e-chat-${run}-${tag}@example.com`);
  await page.getByLabel("Password").fill("correct-horse-9");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
}

/** The conversation list is a permanent sidebar on desktop and a slide-over sheet on mobile. */
async function openHistory(page: Page) {
  const toggle = page.getByRole("button", { name: "Conversation history" });
  if (await toggle.isVisible()) await toggle.click();
  return page.getByRole("navigation", { name: "Conversations" });
}

test("ask a question, inspect the cited source, and open the highlighted page in the PDF viewer", async ({ page }, info) => {
  test.setTimeout(120_000);
  await signUp(page, info.project.name);

  // 1. upload a real two-page PDF and wait for the pipeline to finish
  await page.goto("/upload");
  await expect(page.getByLabel("Choose files to upload")).toBeEnabled();
  await page.getByLabel("Choose files to upload").setInputFiles(path.join(__dirname, "fixtures", "report.pdf"));
  await expect(page.getByText(/uploaded, processing will continue/)).toBeVisible();
  await page.getByRole("link", { name: "Open" }).click();
  await expect(page.getByText("Ready", { exact: true })).toBeVisible({ timeout: 40_000 });

  // 2. ask a grounded question
  await page.goto("/assistant");
  await page.getByLabel("Your question").fill("How did operating margin and logistics costs change?");
  await page.getByRole("button", { name: "Send" }).click();
  const citation = page.getByRole("button", { name: "Open source 1" }).first();
  await expect(citation).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/Operating margin improved as logistics costs fell/).first()).toBeVisible();
  await expect(page).toHaveURL(/\/assistant\?c=/);

  // 3. the conversation was titled from the question and listed
  const list = await openHistory(page);
  await expect(list.getByText(/How did operating margin/)).toBeVisible();
  // On mobile the list is a modal sheet: close it so the rest of the page is interactive again.
  if (await page.getByRole("dialog").count()) {
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
  }

  // 4. open the source panel: shows the passage and the real page number
  await citation.click();
  const panel = page.getByRole("dialog");
  await expect(panel.getByText("Page 1")).toBeVisible();
  await expect(panel.getByText(/logistics costs fell/)).toBeVisible();

  // 5. jump into the viewer at that page with the passage highlighted
  await panel.getByRole("link", { name: /Open in document/ }).click();
  await expect(page).toHaveURL(/\/documents\/.+\/view\?page=1/);
  await expect(page.getByTestId("pdf-page").locator("canvas")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".textLayer span.dm-hl-cite").first()).toBeVisible({ timeout: 30_000 });

  // 6. in-document search finds a term on the second page and navigates there
  await page.getByLabel("Search in document").fill("mitochondria");
  await expect(page.getByText(/\d+ on 1 page/)).toBeVisible();
  await page.getByRole("button", { name: "Next match" }).click();
  await expect(page.getByLabel("Page number")).toHaveValue("2");
  await expect(page.locator(".textLayer span.dm-hl").first()).toBeVisible({ timeout: 15_000 });

  // 7. page navigation and zoom controls work
  await page.getByRole("button", { name: "Previous page" }).click();
  await expect(page.getByLabel("Page number")).toHaveValue("1");
  await page.getByRole("button", { name: "Zoom in" }).click();
  await expect(page.getByText("150%")).toBeVisible();
});

test("an unanswerable question says so without citations; feedback, rename and delete work", async ({ page }, info) => {
  test.setTimeout(120_000);
  await signUp(page, `b-${info.project.name}`);
  await page.goto("/upload");
  await expect(page.getByLabel("Choose files to upload")).toBeEnabled();
  await page.getByLabel("Choose files to upload").setInputFiles(path.join(__dirname, "fixtures", "report.pdf"));
  await page.getByRole("link", { name: "Open" }).click();
  await expect(page.getByText("Ready", { exact: true })).toBeVisible({ timeout: 40_000 });

  await page.goto("/assistant");
  await page.getByLabel("Your question").fill("zzqx flurbnak quuxington?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText(/couldn't find enough evidence/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByLabel("Sources")).toHaveCount(0);

  await page.getByRole("button", { name: "Good answer" }).click();
  await expect(page.getByRole("button", { name: "Good answer" })).toHaveAttribute("aria-pressed", "true");

  await openHistory(page);
  await page.getByRole("button", { name: /Actions for/ }).click();
  await page.getByRole("menuitem", { name: "Rename" }).click();
  await page.getByLabel("Conversation title").fill("Renamed chat");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("navigation", { name: "Conversations" }).getByText("Renamed chat")).toBeVisible();

  await page.getByRole("button", { name: /Actions for/ }).click();
  await page.getByRole("menuitem", { name: "Delete" }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await openHistory(page);
  await expect(page.getByText("No conversations yet.").filter({ visible: true })).toBeVisible();
});
