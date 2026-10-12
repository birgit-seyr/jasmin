import { defineConfig, devices } from "@playwright/test";
import { BASE_URL } from "./support/env";

const inCi = Boolean(process.env.CI);

export default defineConfig({
  testDir: "./tests",
  // Every test shares the e2e tenant's schema, the same reason pytest never
  // runs two sessions at once.
  workers: 1,
  fullyParallel: false,
  forbidOnly: inCi,
  // A retry that passes is still reported as flaky.
  retries: inCi ? 1 : 0,
  // On a fresh CI stack, Vite compiles the app on its first request.
  expect: { timeout: inCi ? 15_000 : 5_000 },
  timeout: inCi ? 60_000 : 30_000,
  reporter: inCi
    ? [["list"], ["html", { open: "never" }], ["github"]]
    : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: BASE_URL,
    // The E2E tenants and personas are seeded in English; the browser's
    // language decides only the login page, before a user is known.
    locale: "en-US",
    timezoneId: "Europe/Berlin",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "setup",
      testMatch: /.*\.setup\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "chromium",
      testMatch: /.*\.spec\.ts/,
      dependencies: ["setup"],
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
