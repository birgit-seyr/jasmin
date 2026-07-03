import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

// Separate from vite.config.js so the prod build stays untouched and tests
// don't pick up the dev proxy / minifier.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@app": path.resolve(__dirname, "./src/app"),
      "@shared": path.resolve(__dirname, "./src/shared"),
      "@features": path.resolve(__dirname, "./src/features"),
      "@hooks": path.resolve(__dirname, "./src/shared/hooks"),
      "@routing": path.resolve(__dirname, "./src/app/routing"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // Keep node_modules and build artefacts out. Also exclude
    // ``*.census.test.tsx`` from the default run — those tests
    // (currently just ``renderCensus.census.test.tsx``) mount every
    // page in the app inside a single test worker and can swell to
    // several GB. Run them on demand with ``npm run test:census``.
    exclude: [
      "node_modules",
      "dist",
      ".vite",
      "**/*.census.test.tsx",
    ],
    // Pre-2026-06-08: a vitest crash mid-suite (the renderCensus
    // worker hit ``Channel closed``) left 10 zombie workers each
    // burning ~22% CPU and inflating to ~425 GB virtual memory —
    // VS Code became unusable until the orphans were killed. Two
    // layers of defence below + a ``pretest`` pkill hook in
    // ``package.json`` so a freshly-started ``npm test`` always
    // starts from a clean slate.
    poolOptions: {
      forks: {
        // Cap concurrent worker processes. Vitest's forks pool otherwise
        // spawns ~one fork per CPU core. The danger isn't steady-state
        // (that worked fine) — it's the failure mode: when a worker
        // crashes mid-suite (e.g. an MSW ``onUnhandledRequest:'error'``
        // rejection settling during teardown → "Channel closed" /
        // ERR_IPC_CHANNEL_CLOSED), forks can orphan and pile up. With no
        // cap that pileup balloons (the 425 GB incident above) and can
        // take the whole machine down. Bounding live forks bounds the
        // blast radius so a single crash can't exhaust a 16 GB Mac.
        maxForks: 4,
        minForks: 1,
        // 2 GB per worker. A test that genuinely needs more will
        // fail loudly with ``JavaScript heap out of memory`` —
        // easier to diagnose than a generic "Channel closed" worker
        // crash, and bounded so OS swap doesn't thrash and starve
        // the parent / VS Code.
        execArgv: ["--max-old-space-size=2048"],
      },
    },
    // Per-test budget. Anything legitimately slower than this
    // (build-time integration, large MSW chain) should be marked
    // ``.slow`` and excluded from the default run; everything else
    // failing this is almost certainly a hang.
    testTimeout: 30_000,
    hookTimeout: 30_000,
  },
});
