/**
 * Tag colours per ConsentKind.
 *
 * Kept here (not inline in each component) so the member portal,
 * the configuration page, and any future surface use the same
 * colour for "privacy" / "sepa" / "withdrawal" / "terms" — a
 * reader scanning multiple pages gets the same colour cue for the
 * same kind everywhere.
 *
 * Values are antd Tag preset colours (see
 * https://ant.design/components/tag#preset-colors). Stick to
 * presets so they auto-adjust to light/dark theme; don't hard-code
 * hex values here.
 */
export const CONSENT_KIND_TAG_COLOR: Record<string, string> = {
  privacy: "blue",
  sepa: "geekblue",
  withdrawal: "orange",
  terms: "purple",
};

/** Lookup with a safe default so unknown / future kinds still render. */
export const consentKindTagColor = (kind: string | undefined): string =>
  (kind && CONSENT_KIND_TAG_COLOR[kind]) || "default";
