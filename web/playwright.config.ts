import { defineConfig, devices } from "@playwright/test";

/**
 * Runs against the production build with no Supabase credentials present.
 *
 * That is the point rather than a limitation: it means CI can prove the app
 * boots, every route renders, the auth form is reachable and the unconfigured
 * state is handled — all without a database and without secrets in the runner.
 * Anything that genuinely needs a live project belongs in a separate suite with
 * its own credentials, not smuggled into the default gate.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://localhost:3210",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run build && npm run start -- --port 3210",
    url: "http://localhost:3210",
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
