import { defineConfig } from "vitest/config";

import baseConfig from "./vitest.config";

// The base config EXCLUDES ``*.census.test.tsx`` from the default ``npm test``
// (those tests mount every page in the app inside one worker and can swell to
// several GB). Vitest applies that ``exclude`` to explicit file arguments too,
// so ``vitest run … renderCensus.census.test.tsx`` against the base config
// reports "No test files found" — the census was impossible to run via its own
// script.
//
// This config reuses everything from the base (plugins, aliases, and — most
// importantly for the memory-heavy census — the fork cap + per-worker heap
// limit) but drops the census exclude and targets ONLY the census file, so
// ``npm run test:census`` actually executes the suite.
const base = baseConfig as unknown as {
  test?: Record<string, unknown>;
  [key: string]: unknown;
};

export default defineConfig({
  ...base,
  test: {
    ...(base.test ?? {}),
    exclude: ["node_modules", "dist", ".vite"],
    include: ["src/test/**/*.census.test.tsx"],
  },
});
