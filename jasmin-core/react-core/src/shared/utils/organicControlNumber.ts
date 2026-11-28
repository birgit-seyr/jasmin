/**
 * The control number the farm's organic surfaces go by: the stored one,
 * trimmed, while its organic documentation is on
 * (``uses_organic_documentation``), else "". Free of hooks and of the i18n
 * setup, so the reseller documents' settings apply the same rule as the
 * office-side ``useOrganicGate`` without pulling either in.
 */
export function organicControlNumberOf(
  tenant: unknown,
  getSetting: (key: string, defaultValue?: unknown) => unknown,
): string {
  if (!getSetting("uses_organic_documentation", true)) return "";
  const raw = (tenant as { organic_control_number?: string | null } | null)
    ?.organic_control_number;
  return (raw ?? "").trim();
}
