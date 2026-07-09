import type { TFunction } from "i18next";

import { useTenant } from "./useTenant";

export type OrganicStatus = "organic" | "in_conversion" | "conventional";

/**
 * Tenant-level gate for the EU 2018/848 organic-status feature.
 *
 * The whole concept (per-article status field on ShareArticle, badges
 * in member-facing views, "*" / "**" markers on PDFs, control-number
 * footer) is contingent on the tenant being certified — i.e. having
 * a non-empty ``Tenant.organic_control_number``. A tenant without
 * one is, by definition, not entitled to label anything as "Bio"
 * or "Umstellung", so every UI surface hides the column/badge/dropdown.
 *
 * Call this hook at the top of any component that renders an
 * organic-status surface; gate the render on ``enabled``.
 */
export function useOrganicGate(): {
  enabled: boolean;
  controlNumber: string;
} {
  const { tenant } = useTenant();
  const raw = (tenant as { organic_control_number?: string | null } | null)
    ?.organic_control_number;
  const controlNumber = (raw ?? "").trim();
  return {
    enabled: controlNumber.length > 0,
    controlNumber,
  };
}

/** i18n-aware label for office-facing dropdowns + member-facing tags.
 *
 * Plain function (not a hook) so it's callable from non-component
 * contexts like memos that build column configs. Mirrors the
 * ``getVegetableSizeLabelPure`` / ``getUnitLabelPure`` pattern in pdfBase —
 * the caller passes its ``t`` instance in. Defaults match the German
 * UI strings used elsewhere in the app. */
export function organicStatusLabel(
  t: TFunction,
  status: OrganicStatus | undefined,
): string {
  switch (status) {
    case "organic":
      return t("commissioning.organic.organic");
    case "in_conversion":
      return t("commissioning.organic.in_conversion");
    case "conventional":
    default:
      return t("commissioning.organic.conventional");
  }
}

/** Options array used by both the office-side select dropdown on the
 * ShareArticle edit screen AND any consumer that needs to translate
 * a saved status to its display label (e.g. an EditableTable
 * ``render`` function). Centralised here so the option set is a single
 * source of truth — adding a new ``OrganicStatus`` case in future
 * only requires updating one place. */
export function organicStatusOptions(
  t: TFunction,
): { value: OrganicStatus; label: string }[] {
  return [
    { value: "conventional", label: organicStatusLabel(t, "conventional") },
    { value: "in_conversion", label: organicStatusLabel(t, "in_conversion") },
    { value: "organic", label: organicStatusLabel(t, "organic") },
  ];
}

/** Ant Design Tag color matching the labels above. ``undefined`` for
 * conventional so the caller can skip rendering entirely. */
export function organicStatusTagColor(
  status: OrganicStatus | undefined,
): string | undefined {
  if (status === "organic") return "green";
  if (status === "in_conversion") return "orange";
  return undefined;
}
