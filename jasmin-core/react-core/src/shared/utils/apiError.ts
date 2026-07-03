import type { AxiosError } from "axios";
import i18n from "@shared/i18n";

/**
 * Canonical error payload produced by `core.exception_handler` on the
 * backend. Every API error response carries this shape:
 *
 *   { code, message, field?, details?, request_id? }
 *
 * Legacy/un-migrated endpoints may still return `{ error: "..." }` or
 * DRF's `{ detail: "..." }` / `{ <field>: ["..."] }` shapes — the helpers
 * here transparently fall back to those so callers never need to branch.
 */
export interface JasminErrorPayload {
  code?: string;
  message?: string;
  field?: string | null;
  details?: Record<string, unknown>;
  request_id?: string;
  // Legacy shapes — read but do not write:
  error?: string;
  detail?: string;
  [key: string]: unknown;
}

/**
 * Narrow an unknown caught value to an Axios error, returning `null` for
 * anything else (network blips, non-axios throws, browser bugs).
 */
function asAxiosError(
  err: unknown,
): AxiosError<JasminErrorPayload> | null {
  if (
    err &&
    typeof err === "object" &&
    "isAxiosError" in err &&
    (err as AxiosError).isAxiosError === true
  ) {
    return err as AxiosError<JasminErrorPayload>;
  }
  return null;
}

/**
 * Return the most relevant message for a caught error, falling back through
 * every known response shape and finally the JS error message.
 *
 * Usage:
 *
 *   try { await api.doThing(); }
 *   catch (err) { notify.error(getErrorMessage(err, "Something failed")); }
 */
export function getErrorMessage(err: unknown, fallback = "Request failed"): string {
  // First: try a frontend-side translation by stable error code. This covers
  // our custom JasminError subclasses (e.g. "commissioning.share_days_locked"),
  // which the backend does NOT translate — see `errors.json` for the keyed
  // strings. Falls through silently when the code is unknown so DRF/Django's
  // already-translated `message` field remains the default.
  const translated = translateByCode(err);
  if (translated) return translated;

  const axiosErr = asAxiosError(err);
  if (axiosErr) {
    const data = axiosErr.response?.data;
    if (data) {
      // Canonical Jasmin shape.
      if (typeof data.message === "string" && data.message) return data.message;
      // Legacy {"error": "..."} shape — still in use on un-migrated endpoints.
      if (typeof data.error === "string" && data.error) return data.error;
      // DRF default {"detail": "..."} shape (used by some 3rd-party DRF code paths).
      if (typeof data.detail === "string" && data.detail) return data.detail;
      // DRF serializer errors: {"field_name": ["err1", ...], ...}
      const fieldMsg = firstFieldMessage(data);
      if (fieldMsg) return fieldMsg;
    }
    if (axiosErr.message) return axiosErr.message;
  }
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

/**
 * Look up an authored, localized message for a known JasminError code.
 *
 * Custom backend errors (subclasses of JasminError) carry only a plain
 * English message. The stable `code` field is the durable identifier we
 * can map to i18n keys on the frontend — e.g.
 * `"commissioning.share_days_locked"` -> `errors.commissioning.share_days_locked`.
 *
 * Returns `undefined` for legacy endpoints with no code, codes that don't
 * have an entry yet, or DRF default codes like `"validation_error"` (those
 * are already translated server-side; trust the backend's `message`).
 *
 * The error's `details` are passed to i18next as interpolation values, so a
 * keyed message can render specifics (e.g. `{{total}}`, `{{minimum}}`). A
 * `details.context` value selects an i18next variant
 * (`errors.<code>_<context>`) — used by errors whose phrasing changes by
 * case, like a two-sided range vs. a single bound.
 */
function translateByCode(err: unknown): string | undefined {
  const code = getErrorCode(err);
  if (!code) return undefined;
  // DRF/Django generic codes pass through to the already-translated message.
  if (code === "validation_error" || code === "not_authenticated") return undefined;
  const key = `errors.${code}`;
  const details = getErrorDetails(err);
  const translated = i18n.t(key, details);
  return translated && translated !== key ? translated : undefined;
}

/**
 * Return the stable machine-readable error code, e.g. `"share.past_week"`.
 * Useful for branching on specific failure modes:
 *
 *   if (getErrorCode(err) === "stock.insufficient") openStockModal();
 *
 * Returns `undefined` for legacy endpoints that don't emit a code yet.
 */
export function getErrorCode(err: unknown): string | undefined {
  const data = asAxiosError(err)?.response?.data;
  return typeof data?.code === "string" ? data.code : undefined;
}

// Internal helper for ``getErrorMessage``.
function getErrorDetails(err: unknown): Record<string, unknown> | undefined {
  const data = asAxiosError(err)?.response?.data;
  if (data?.details && typeof data.details === "object") {
    return data.details as Record<string, unknown>;
  }
  return undefined;
}

function firstFieldMessage(data: JasminErrorPayload): string | undefined {
  for (const [key, value] of Object.entries(data)) {
    if (["code", "message", "field", "details", "request_id", "error", "detail"].includes(key)) {
      continue;
    }
    if (Array.isArray(value) && value.length > 0 && typeof value[0] === "string") {
      return value[0];
    }
    if (typeof value === "string" && value) return value;
  }
  return undefined;
}
