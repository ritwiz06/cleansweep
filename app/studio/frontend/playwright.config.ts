import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

// e2e/serve.py serves Studio offline: the shipped recordings, the committed results and the
// test fixtures. PYTHON overrides the interpreter (default: the repository's .venv).
const venv = fileURLToPath(new URL("../../../.venv/bin/python", import.meta.url));
const python = process.env.PYTHON || (existsSync(venv) ? venv : "python3");
const port = Number(process.env.STUDIO_E2E_PORT || 8799);

export default defineConfig({
  testDir: "e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1280, height: 720 },
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 720 } } }],
  webServer: {
    command: `"${python}" e2e/serve.py ${port}`,
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
