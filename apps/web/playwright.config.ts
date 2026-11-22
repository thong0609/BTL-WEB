import { defineConfig } from "@playwright/test";

// API responses are intercepted by these UI tests; no shared database/broker is used.
export default defineConfig({
  testDir: "./tests/browser",
  fullyParallel: false,
  workers: 1,
  timeout: 45_000,
  retries: 0,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:3191", trace: "retain-on-failure", screenshot: "only-on-failure" },
  webServer: {
    command: "node node_modules/next/dist/bin/next dev --webpack --hostname 127.0.0.1 --port 3191",
    url: "http://127.0.0.1:3191",
    reuseExistingServer: false,
    timeout: 120_000,
    env: { GATEWAY_URL: "http://127.0.0.1:3192", NEXT_TELEMETRY_DISABLED: "1" },
  },
});
