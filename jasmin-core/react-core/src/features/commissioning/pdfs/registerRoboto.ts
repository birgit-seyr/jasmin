/**
 * Register the Roboto font family for @react-pdf/renderer, once per app.
 *
 * Previously each PDF entry point registered Roboto from cdnjs.cloudflare.com.
 * That had three problems: (1) GDPR — fetching from a US CDN sends the user's
 * IP to Cloudflare every time a PDF is opened; (2) reliability — PDF rendering
 * fails on network outages; (3) the URL path (`/ajax/libs/ink/3.1.10/`)
 * pinned to an unrelated 2014-era CSS framework's mirror of Roboto.
 *
 * This module imports the .woff files from `@fontsource/roboto` and registers
 * them locally. Vite emits them into `dist/assets/woff/` so they're served
 * from the same origin as the app — no third-party request.
 *
 * Import this module once for its side effect; subsequent imports are no-ops
 * because ES module evaluation runs once.
 */

import { Font } from "@react-pdf/renderer";
import roboto300 from "@fontsource/roboto/files/roboto-latin-300-normal.woff?url";
import roboto400 from "@fontsource/roboto/files/roboto-latin-400-normal.woff?url";
import roboto400italic from "@fontsource/roboto/files/roboto-latin-400-italic.woff?url";
import roboto500 from "@fontsource/roboto/files/roboto-latin-500-normal.woff?url";
import roboto700 from "@fontsource/roboto/files/roboto-latin-700-normal.woff?url";
import roboto700italic from "@fontsource/roboto/files/roboto-latin-700-italic.woff?url";

// Vite's `?url` plugin gives us a same-origin asset URL like
// "/assets/woff/roboto-latin-400-normal-XXXX.woff" (or "/node_modules/..." in
// dev / vitest). In the browser the path is fetched HTTP — no third-party
// request, no Cloudflare leak.
//
// In Node (PDF generation tests), @react-pdf uses fontkit which reads via
// `fs.open(path)` — root-relative paths from Vite get interpreted as starting
// at filesystem `/`, which doesn't exist. We prepend `process.cwd()` to turn
// them into absolute paths fontkit can read. No network involved either way.
const isNode = typeof window === "undefined";
const toFsPath = (viteUrl: string): string =>
  isNode && viteUrl.startsWith("/") ? `${process.cwd()}${viteUrl}` : viteUrl;

Font.register({
  family: "Roboto",
  fonts: [
    { src: toFsPath(roboto300), fontWeight: 300 },
    { src: toFsPath(roboto400), fontWeight: 400 },
    { src: toFsPath(roboto400italic), fontWeight: 400, fontStyle: "italic" },
    { src: toFsPath(roboto500), fontWeight: 500 },
    { src: toFsPath(roboto700), fontWeight: 700 },
    { src: toFsPath(roboto700italic), fontWeight: 700, fontStyle: "italic" },
  ],
});
