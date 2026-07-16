/**
 * Auto-captured, non-sensitive page context sent with a new ticket so the
 * super-admin knows where the user hit the problem. Captured at SUBMIT (not
 * mount) so ``page_path`` reflects where the user actually was. The backend
 * re-sanitizes (allowlists keys + strips query strings) — never trust this to
 * be clean, and never send tenant/identity from here.
 */
export function captureSupportContext(): Record<string, string> {
  return {
    // pathname only — no query string (the backend strips it anyway, but keep
    // signed ?st= tokens out of the payload at the source too).
    page_path: window.location.pathname,
    user_agent: navigator.userAgent,
    viewport: `${window.innerWidth}x${window.innerHeight}`,
    locale: document.documentElement.lang || navigator.language,
  };
}
