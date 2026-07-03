// Register all dayjs plugins on the singleton before anything renders.
// Must stay first so no lazily-loaded chunk can mount a date widget before
// its required plugin (isoWeek / customParseFormat / …) is available.
import "@shared/utils/dayjsSetup";
import { Buffer } from "buffer";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import * as Sentry from "@sentry/react";
import App from "./App";
import { reloadOnceForChunkError } from "@shared/utils/chunkReload";
import "@shared/i18n";

// Error monitoring (Sentry-compatible, points at self-hosted GlitchTip).
// No-op when ``VITE_SENTRY_DSN`` is empty — keeps dev builds free of
// noisy outbound requests. The DSN is set at build time by Vite, so
// ``npm run build`` needs to run with the env var in scope to embed it
// (already wired in docker-compose.yml via build args + .env).
if (import.meta.env.VITE_SENTRY_DSN) {
  Sentry.init({
    dsn: import.meta.env.VITE_SENTRY_DSN,
    environment: import.meta.env.PROD ? "production" : "development",
    // 5% performance-trace sampling matches the backend.
    tracesSampleRate: 0.05,
    // GDPR: GlitchTip doesn't need a user's IP / email by default.
    // Attach them per-event via ``Sentry.setUser({...})`` after a
    // logged-in session, behind whatever consent gating you want.
    sendDefaultPii: false,
  });
}

// @react-pdf/renderer's internal image loader references Node's `Buffer`
// when fetching remote images. Expose the polyfill as a browser global
// so PDF generation works outside Node.
const globalScope = globalThis as typeof globalThis & {
  Buffer?: typeof Buffer;
};
if (typeof globalScope.Buffer === "undefined") {
  globalScope.Buffer = Buffer;
}
// Variable Inter font — one woff2 covers every weight (100-900) via
// the OpenType variations table. Replaces 6 individual weight CSS
// imports (200/300/400/500/600/700) that previously shipped ~180 KB
// of CSS-with-fonts in the main bundle.
// PDF generation still uses @fontsource/roboto static weights (see
// components/pdfs/registerRoboto.ts) because @react-pdf/renderer
// expects per-weight font files at Font.register() time.
import "@fontsource-variable/inter";
import "@shared/styles/index.css";

// This app no longer ships a service worker, but older builds did. A leftover
// SW lives in the BROWSER PROFILE (a fresh build/container doesn't clear it),
// intercepts fetches, and serves stale chunks/HTML — a silent white page with no
// console error, historically only escapable via "clear site data" (Firefox is
// especially prone: an unregistered worker keeps controlling existing clients).
// This guard self-heals it: if a worker controls the page, purge it and
// hard-reload ONCE into a clean, worker-free load BEFORE mounting the app.
const SW_RELOAD_FLAG = "sw-cleanup-reloaded";

function renderApp() {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

// sessionStorage access can THROW a SecurityError when the browser blocks
// storage for the site (Firefox ETP / "block cookies") — never let the loop
// guard itself keep the app from mounting.
function safeSession(op: (store: Storage) => void): void {
  try {
    op(window.sessionStorage);
  } catch {
    /* storage blocked — ignore */
  }
}

async function purgeServiceWorkers(): Promise<void> {
  const registrations = await navigator.serviceWorker.getRegistrations();
  await Promise.all(registrations.map((reg) => reg.unregister()));
  if ("caches" in window) {
    const keys = await caches.keys();
    await Promise.all(keys.map((key) => caches.delete(key)));
  }
}

function bootstrap(): void {
  // No SW support, or this load isn't controlled by a worker (the common case):
  // mount immediately. Purge any stray, non-controlling registration in the
  // background — it isn't intercepting THIS load, so no reload is needed.
  if (!("serviceWorker" in navigator) || !navigator.serviceWorker.controller) {
    if ("serviceWorker" in navigator) {
      purgeServiceWorkers().catch((err) =>
        console.warn("SW cleanup failed:", err),
      );
    }
    safeSession((store) => store.removeItem(SW_RELOAD_FLAG));
    renderApp();
    return;
  }

  // The page IS controlled by a leftover worker whose fetches may serve stale
  // assets. If we already reloaded once and it STILL controls the page, mount
  // anyway rather than loop ("clear site data" remains the manual escape hatch).
  let alreadyReloaded = false;
  safeSession((store) => {
    alreadyReloaded = store.getItem(SW_RELOAD_FLAG) === "1";
  });
  if (alreadyReloaded) {
    console.warn(
      "Service worker still controlling after cleanup; mounting anyway.",
    );
    renderApp();
    return;
  }

  // Purge the worker + caches, then hard-reload into a clean load. Do NOT render
  // here — we're navigating away, and rendering now would paint a stale page.
  safeSession((store) => store.setItem(SW_RELOAD_FLAG, "1"));
  console.warn(
    "Leftover service worker controlling page; cleaning up and reloading…",
  );
  purgeServiceWorkers()
    .catch((err) => console.warn("SW cleanup failed:", err))
    .finally(() => window.location.reload());
}

// A lazy route chunk failed to load (Vite's PRODUCTION-only preload event) —
// almost always a stale reference after a deploy: this still-open tab points at
// an old ``assets/js/<name>-<oldhash>.js`` the new build removed (→ 404). Reload
// once to fetch the no-cache index.html + current hashes so the import resolves.
// The same failure in the dev server (where this event isn't emitted) is caught
// by the global ErrorBoundary; both go through ``reloadOnceForChunkError`` so
// they share ONE loop-guard against reload-storming a genuinely broken chunk.
window.addEventListener("vite:preloadError", (event: Event) => {
  if (reloadOnceForChunkError()) event.preventDefault();
});

try {
  bootstrap();
} catch (err) {
  // The guard must never be the reason the app fails to mount.
  console.warn(
    "Service-worker bootstrap guard failed; mounting directly:",
    err,
  );
  renderApp();
}
