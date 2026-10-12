import { getErrorStatus } from "@shared/utils/apiError";

const MAX_QUERY_RETRIES = 3;

/**
 * Whether a failed query is tried again. A client error (4xx) answers the
 * same on every try — a missing record stays missing, a refused permission
 * stays refused — so it is shown at once; a 401 is the axios interceptor's
 * to handle. A network error or a server error (5xx) may pass, so those are
 * retried up to three times.
 */
export function shouldRetryQuery(
  failureCount: number,
  error: unknown,
): boolean {
  const status = getErrorStatus(error);
  if (status !== undefined && status >= 400 && status < 500) return false;
  return failureCount < MAX_QUERY_RETRIES;
}
