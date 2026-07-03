// Mirror the app's boot-time dayjs plugin registration (see main.tsx) so
// component/hook tests run against the same singleton the app has.
import "@shared/utils/dayjsSetup";
import "@testing-library/jest-dom/vitest";
// vitest-axe: the runtime axe matcher `toHaveNoViolations`, so component tests
// can assert `expect(await axe(container)).toHaveNoViolations()` — the layer
// that catches rendered-DOM a11y issues jsx-a11y (static, raw-JSX) can't see.
// The package's `extend-expect` entry ships an EMPTY runtime file (0.1.0
// packaging bug) — it only supplies the TS augmentation — so the matcher must
// be registered explicitly via expect.extend below.
import "vitest-axe/extend-expect"; // type augmentation for `toHaveNoViolations`
import * as axeMatchers from "vitest-axe/matchers";
import { afterAll, afterEach, beforeAll, expect, vi } from "vitest";
import { cleanup } from "@testing-library/react";

expect.extend(axeMatchers);

import { server } from "./msw/server";

// Friendly Captcha SDK registers a ``<frc-captcha>`` custom element
// on import side-effect. jsdom supports customElements but the SDK
// also tries to set up a SharedWorker / Web Worker that jsdom doesn't
// provide. Replace with a no-op module so importing pages that mount
// the widget (LoginPage, RegisterPage, …) doesn't crash the suite.
// The ``<FriendlyCaptcha>`` component additionally returns null when
// ``tenant.friendly_captcha_sitekey`` is empty (the default in tests),
// so nothing actually renders.
vi.mock("@friendlycaptcha/sdk", () => ({}));

// MSW intercepts every HTTP call. Tests that don't expect any traffic stay
// quiet; tests that do supply handlers via `server.use(...)` per case.
// Custom warn callback so non-HTTP fetches (e.g. yoga.wasm pulled in by
// @react-pdf/renderer) don't dump a binary blob into the test output.
beforeAll(() =>
  server.listen({
    onUnhandledRequest: (req, print) => {
      const url = req.url;
      // Static assets / wasm binaries used by libraries during import.
      if (/\.(wasm|woff2?|ttf|otf|png|jpe?g|gif|svg)(\?|$)/.test(url)) return;
      print.error();
    },
  }),
);
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// Reset DOM between tests so RTL components don't leak state.
// In a node-environment test file (e.g. PDF generation), window/localStorage
// don't exist, so guard each side-effect.
afterEach(() => {
  cleanup();
  if (typeof localStorage !== "undefined") {
    localStorage.clear();
  }
  vi.restoreAllMocks();
});

// AntD's Modal/Drawer measure the scrollbar width by reading the
// ``::-webkit-scrollbar`` pseudo-element via ``getComputedStyle(el, pseudoElt)``
// (rc-util ``getScrollBarSize``). jsdom has no layout engine and emits a noisy
// "Not implemented: window.getComputedStyle(elt, pseudoElt)" jsdomError for the
// pseudo-element form — it still returns a style object, so it is log noise, not
// a failure. Drop the pseudo argument so every modal-opening test falls back to
// the supported single-arg path (the measured scrollbar width is 0 in jsdom
// either way, since there is no real layout).
if (typeof window !== "undefined") {
  const realGetComputedStyle = window.getComputedStyle.bind(window);
  window.getComputedStyle = ((element: Element) =>
    realGetComputedStyle(element)) as typeof window.getComputedStyle;
}

// Some libraries (antd, MUI) probe matchMedia. jsdom doesn't ship it.
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
}
