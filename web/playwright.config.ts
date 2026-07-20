import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  retries: 1,
  use: { baseURL: "http://127.0.0.1:5180", trace: "on-first-retry" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], channel: "chrome" } }],
  webServer: {
    command: "bash ../tools/start_e2e_stack.sh",
    url: "http://127.0.0.1:5180",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
