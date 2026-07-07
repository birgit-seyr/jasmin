/**
 * Allowlist of URL schemes that are safe to bind to an anchor ``href``.
 * Everything else — notably ``javascript:``, ``data:``, ``vbscript:`` — is
 * rejected to prevent stored-XSS via user/tenant-controlled links.
 */
const SAFE_SCHEMES = ["http:", "https:", "mailto:", "tel:"];

/**
 * Normalize a user/tenant-controlled URL for use as an anchor ``href``.
 *
 * Returns the trimmed URL when it uses a safe scheme (http/https/mailto/tel)
 * or is a relative path resolved against the app origin. Returns ``undefined``
 * for anything else (e.g. a ``javascript:`` or ``data:`` payload) so the caller
 * renders no clickable link instead of an XSS vector.
 */
export function safeExternalHref(
  url: string | null | undefined,
): string | undefined {
  if (!url) return undefined;
  const trimmed = url.trim();
  if (!trimmed) return undefined;
  try {
    // Resolve against the current origin so relative paths are accepted and
    // the scheme of absolute URLs can be inspected.
    const parsed = new URL(trimmed, window.location.origin);
    if (SAFE_SCHEMES.includes(parsed.protocol)) {
      return trimmed;
    }
  } catch {
    // Not a parseable URL — treat as unsafe.
    return undefined;
  }
  return undefined;
}
