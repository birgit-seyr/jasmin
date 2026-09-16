/**
 * Shared email-status color logic for the office email log
 * (EmailLog) and the per-member emails modal (MemberEmailsModal),
 * so a new provider status renders the same tag color in both views.
 */

// Statuses where the office needs to look — red tag.
export const DANGER_STATUSES = new Set([
  "bounced",
  "rejected",
  "failed",
  "complained",
]);
export const WARN_STATUSES = new Set(["deferred", "pending"]);
// Deliberately not sent (onboarding mode): nothing went wrong, nothing to do.
export const NEUTRAL_STATUSES = new Set(["suppressed"]);

/** Tag color for an email-provider status: danger→red, warn→orange,
 *  delivered→green, neutral→grey (AntD ``default``), everything else→blue. */
export function getEmailStatusColor(status: string): string {
  if (DANGER_STATUSES.has(status)) return "red";
  if (WARN_STATUSES.has(status)) return "orange";
  if (NEUTRAL_STATUSES.has(status)) return "default";
  if (status === "delivered") return "green";
  return "blue";
}
