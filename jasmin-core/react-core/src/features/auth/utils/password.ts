/**
 * Quick client-side password strength estimator (0–4).
 *
 * Real validation happens on the server (zxcvbn ≥ 3) — this is only a UX
 * affordance to nudge users towards a passing password without a round-trip.
 */
export function clientPasswordScore(pw: string): number {
  if (!pw) return 0;
  let score = 0;
  if (pw.length >= 12) score++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) score++;
  if (/[0-9]/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  if (pw.length >= 16) score++;
  return Math.min(score, 4);
}

/**
 * AntD rule builder for the "confirm password matches" field. Use it inside a
 * function rule so it can read the sibling ``password`` field:
 *
 * ```tsx
 * ({ getFieldValue }) => passwordConfirmValidator(getFieldValue, t("…mismatch"))
 * ```
 */
export function passwordConfirmValidator(
  getFieldValue: (name: string) => unknown,
  message: string,
) {
  return {
    validator(_rule: unknown, value: string) {
      if (!value || getFieldValue("password") === value) {
        return Promise.resolve();
      }
      return Promise.reject(new Error(message));
    },
  };
}
