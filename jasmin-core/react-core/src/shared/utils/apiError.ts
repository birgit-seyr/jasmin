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

let formatDetailDate: ((isoDate: string) => string) | null = null;

/**
 * Lets error messages show dates in the tenant's format. `getErrorMessage` is
 * a plain function with no access to the tenant, so the tenant app hands it
 * the tenant's formatter once (`useErrorDateFormat`); without one, a date in
 * an error's `details` stays ISO.
 */
export function setErrorDateFormatter(
  formatter: ((isoDate: string) => string) | null,
): void {
  formatDetailDate = formatter;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** `details` with every ISO date (`YYYY-MM-DD`) in the tenant's format. */
function withDisplayDates(
  details: Record<string, unknown> | undefined,
): Record<string, unknown> | undefined {
  const format = formatDetailDate;
  if (!details || !format) return details;
  return Object.fromEntries(
    Object.entries(details).map(([key, value]) => [
      key,
      typeof value === "string" && ISO_DATE.test(value) ? format(value) : value,
    ]),
  );
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
 * Return the most relevant message for a caught error: the server's reason
 * (`getServerErrorMessage`), else the caller's `fallback`, else the error's
 * own text.
 *
 * A failed request whose server gave no reason shows the `fallback` rather
 * than axios' own English ("Request failed with status code 503", "Network
 * Error"). A non-request error keeps its message ahead of the fallback, since
 * code throws `new Error(t("…"))` to carry a translated reason.
 *
 * Usage:
 *
 *   try { await api.doThing(); }
 *   catch (err) { notify.error(getErrorMessage(err, t("common.action_failed"))); }
 */
export function getErrorMessage(err: unknown, fallback?: string): string {
  const serverMessage = getServerErrorMessage(err);
  if (serverMessage) return serverMessage;
  const axiosErr = asAxiosError(err);
  if (axiosErr) return fallback || axiosErr.message || "Request failed";
  if (err instanceof Error && err.message) return err.message;
  return fallback || "Request failed";
}

/**
 * The message the server gave for a failed request, or `undefined` when it
 * gave none — an empty body, a network failure, a non-axios throw. Unlike
 * `getErrorMessage` it never falls back to a JS error's own text, so a caller
 * can show its own translated message instead:
 *
 *   notify.error(getServerErrorMessage(err) ?? t("users.resend_failed"));
 */
export function getServerErrorMessage(err: unknown): string | undefined {
  // First: try a frontend-side translation by stable error code. This covers
  // our custom JasminError subclasses (e.g. "commissioning.share_days_locked"),
  // which the backend does NOT translate — see `errors.json` for the keyed
  // strings. Falls through silently when the code is unknown so DRF/Django's
  // already-translated `message` field remains the default.
  const translated = translateByCode(err);
  if (translated) return translated;

  const data = asAxiosError(err)?.response?.data;
  if (!data || typeof data !== "object") return undefined;
  // Canonical Jasmin shape.
  if (typeof data.message === "string" && data.message) return data.message;
  // Legacy {"error": "..."} shape — still in use on un-migrated endpoints.
  if (typeof data.error === "string" && data.error) return data.error;
  // DRF default {"detail": "..."} shape (used by some 3rd-party DRF code paths).
  if (typeof data.detail === "string" && data.detail) return data.detail;
  // DRF serializer errors: {"field_name": ["err1", ...], ...}
  return firstFieldMessage(data);
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
 * keyed message can render specifics (e.g. `{{total}}`, `{{minimum}}`), with
 * ISO dates in the tenant's format (`setErrorDateFormatter`). A
 * `details.context` value selects an i18next variant
 * (`errors.<code>_<context>`) — used by errors whose phrasing changes by
 * case, like a two-sided range vs. a single bound.
 */
function translateByCode(err: unknown): string | undefined {
  const code = getErrorCode(err);
  if (!code) return undefined;
  // DRF/Django generic codes pass through to the already-translated message.
  if (code === "validation_error" || code === "not_authenticated") return undefined;
  return messageForErrorCode(code, getErrorDetails(err));
}

/**
 * The message an API error with this code and these details shows, or
 * `undefined` when the code has no entry. Lets the frontend refuse a change
 * in the very words the backend's refusal of it would be shown in.
 */
export function messageForErrorCode(
  code: string,
  details?: Record<string, unknown>,
): string | undefined {
  const key = `errors.${code}`;
  const translated = i18n.t(key, withDisplayDates(details));
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

/** The HTTP status a request failed with, or `undefined` without a response. */
export function getErrorStatus(err: unknown): number | undefined {
  return asAxiosError(err)?.response?.status;
}

/**
 * Return the structured ``details`` object a JasminError carries (e.g.
 * `{ available, requested }` on an insufficient-stock error), for callers
 * that render the specifics inline rather than as a generic message.
 * Returns ``undefined`` for legacy/detail-less errors.
 */
export function getErrorDetails(
  err: unknown,
): Record<string, unknown> | undefined {
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
