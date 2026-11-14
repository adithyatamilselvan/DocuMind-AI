import { defineConfig, devices } from "@playwright/test";

const FRONTEND = 3100;
const BACKEND = 8100;

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: `http://localhost:${FRONTEND}`, trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: [
    {
      // Isolated e2e database; unique emails per run mean no cleanup is required.
      command: `..\\backend\\.venv\\Scripts\\python -m uvicorn app.main:app --port ${BACKEND}`,
      cwd: "../backend",
      url: `http://localhost:${BACKEND}/health`,
      reuseExistingServer: !process.env.CI,
      env: {
        APP_ENV: "test",
        APP_SECRET_KEY: "e2e-secret-key-e2e-secret-key-e2e-secret-key",
        MONGODB_DB: "documind_e2e",
        RATE_LIMIT_ENABLED: "false",
        // Default: deterministic offline providers so documents genuinely complete the pipeline in e2e.
        // E2E_REAL_AI=1: use the providers from ../.env (e.g. Cohere + local embeddings) and spare Trial quota.
        ...(process.env.E2E_REAL_AI
          ? { RAG_MULTI_QUERY: "false" }
          : { EMBEDDING_PROVIDER: "hashing", LLM_PROVIDER: "fake" }),
        LOCAL_STORAGE_DIR: ".local-data/e2e-objects",
        FRONTEND_URL: `http://localhost:${FRONTEND}`,
      },
    },
    {
      command: `npx next dev -p ${FRONTEND}`,
      url: `http://localhost:${FRONTEND}/login`,
      reuseExistingServer: !process.env.CI,
      env: { BACKEND_INTERNAL_URL: `http://localhost:${BACKEND}` },
    },
  ],
});
