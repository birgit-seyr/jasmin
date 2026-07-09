/**
 * Normalise a list endpoint response to a plain array.
 *
 * Orval sometimes types a paginated DRF endpoint as a bare list (and vice
 * versa), so call sites can't trust the static shape. This defends against
 * both: a real array passes through; a ``{ results }`` page yields its
 * ``results`` (or ``[]`` if absent); anything else (``null`` / ``undefined`` /
 * a non-list object) yields ``[]``.
 *
 * @example
 *   const rows = unwrapList<ChargeSchedule>(chargesData);
 */
export function unwrapList<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[];
  if (data && typeof data === "object" && "results" in data) {
    const results = (data as { results?: T[] }).results;
    return Array.isArray(results) ? results : [];
  }
  return [];
}
