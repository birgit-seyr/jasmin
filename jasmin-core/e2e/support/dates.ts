/**
 * Date helpers for flows that book "next week". The stack runs on the real
 * clock, so every week a test books is computed at run time.
 */

/** The first Monday after today (a week from today when today is a Monday). */
export function nextMonday(today: Date = new Date()): Date {
  const date = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const daysAhead = (8 - date.getDay()) % 7 || 7;
  date.setDate(date.getDate() + daysAhead);
  return date;
}

/** The ISO 8601 week number of ``date``. */
export function isoWeek(date: Date): number {
  const thursday = new Date(
    Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()),
  );
  thursday.setUTCDate(thursday.getUTCDate() + 3 - ((thursday.getUTCDay() + 6) % 7));
  const yearStart = new Date(Date.UTC(thursday.getUTCFullYear(), 0, 1));
  return Math.ceil(((thursday.getTime() - yearStart.getTime()) / 86_400_000 + 1) / 7);
}

/** ``date`` in the tenant's date format; the E2E tenants keep the default. */
export function formatTenantDate(date: Date): string {
  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  return `${day}.${month}.${date.getFullYear()}`;
}
