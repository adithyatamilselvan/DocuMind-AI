// Production-build smoke test: security headers present, no CSP violations on core pages, PDF viewer works under CSP.
// Run:  npm run build && node e2e/prod-smoke.mjs   (needs the API on :8100 with APP_ENV=test, see playwright.config.ts)
import { chromium } from "@playwright/test";
import { spawn } from "node:child_process";
import path from "node:path";

const PORT = 3200;
const env = { ...process.env, PORT: String(PORT), HOSTNAME: "127.0.0.1", NODE_ENV: "production" };
const server = spawn("node", [".next/standalone/server.js"], { env, stdio: "pipe" });
await new Promise((r) => setTimeout(r, 4000));

const base = `http://127.0.0.1:${PORT}`;
let failed = false;
const check = (cond, msg) => { console.log(`${cond ? "PASS" : "FAIL"}  ${msg}`); if (!cond) failed = true; };

try {
  const res = await fetch(`${base}/login`);
  const h = res.headers;
  check(/default-src 'self'/.test(h.get("content-security-policy") ?? ""), "CSP header present");
  check(h.get("x-frame-options") === "DENY", "X-Frame-Options DENY");
  check(h.get("x-content-type-options") === "nosniff", "nosniff");
  check(!/unsafe-eval/.test(h.get("content-security-policy") ?? ""), "no unsafe-eval in production CSP");

  const browser = await chromium.launch();
  const page = await browser.newPage();
  const violations = [];
  page.on("console", (m) => /Content Security Policy|Refused to/i.test(m.text()) && violations.push(m.text()));
  page.on("pageerror", (e) => violations.push(`pageerror: ${e.message}`));
  await page.goto(`${base}/register`);
  await page.getByLabel("Name").fill("Smoke");
  await page.getByLabel("Email").fill(`smoke-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("correct-horse-9");
  await page.getByRole("button", { name: "Create account" }).click();
  await page.waitForURL(/dashboard/, { timeout: 20000 });
  await page.goto(`${base}/upload`);
  await page.getByLabel("Choose files to upload").waitFor();
  await page.waitForFunction(() => !document.querySelector("input[type=file]").disabled);
  await page.getByLabel("Choose files to upload").setInputFiles(path.join("e2e", "fixtures", "report.pdf"));
  await page.getByRole("link", { name: "Open" }).click();
  await page.getByText("Ready", { exact: true }).waitFor({ timeout: 40000 });
  await page.getByRole("link", { name: "View", exact: true }).click();
  await page.locator("[data-testid=pdf-page] canvas").waitFor({ timeout: 30000 });
  check(true, "PDF viewer renders under the production CSP");
  check(violations.length === 0, `no CSP violations or page errors ${violations.join(" | ")}`);
  await browser.close();
} catch (e) {
  check(false, `smoke run error: ${e.message}`);
} finally {
  server.kill();
}
process.exit(failed ? 1 : 0);
