/**
 * Single source of truth for the share-content planning pages/nav.
 *
 * Each active ``share_option`` gets planning views derived from its currently
 * active ``ShareType``:
 *
 *   - ``needs_complex_planning = true``  → a per-week COMPLEX view
 *     (``PlanningShareContentBase``) AND a LONG-TERM view
 *     (``PlanningShareContentLongTermBase``).
 *   - ``needs_complex_planning = false`` → ONLY the long-term view.
 *
 * The complex-vs-long-term decision, the "additional" sidebar section, and the
 * generic-article-column flag are all DATA (read from the ShareType), so adding
 * a share option = one entry here (its slug + i18n label/title keys), not a new
 * page + route + sidebar link.
 *
 * Lives in ``shared/`` (not the commissioning feature) because the shared
 * ``CommissioningSidebar`` consumes it and ``shared/**`` may not import
 * ``@features/*`` (the one-way layering rule).
 */
import { ShareTypeEnum } from "@shared/api/generated/models";

export type PlanningMode = "complex" | "long-term";

export interface PlanningShareOptionConfig {
  shareOption: ShareTypeEnum;
  /** URL segment: ``/commissioning/planning/<slug>[/long-term]``. */
  slug: string;
  /** i18n key for the page ``<h1>`` title, per mode. */
  complexPageTitleKey: string;
  longTermPageTitleKey: string;
  /** i18n key for the page explainer, per mode. */
  complexExplainerKey: string;
  longTermExplainerKey: string;
  /** i18n key for the sidebar link label, per mode. */
  complexSidebarKey: string;
  longTermSidebarKey: string;
}

// Order mirrors the ShareType option order used elsewhere (useShareTypes'
// SHARE_OPTION_ORDER). The sidebar renders complex options in this order,
// then the long-term-only ("additional") options in this order.
export const PLANNING_SHARE_OPTIONS: PlanningShareOptionConfig[] = [
  {
    shareOption: ShareTypeEnum.HARVEST_SHARE,
    slug: "harvest-shares",
    complexPageTitleKey: "commissioning.planning_harvest_shares",
    longTermPageTitleKey: "commissioning.planning_long_term_harvest_share_vegs",
    complexExplainerKey: "explainers.planning_harvest_shares",
    longTermExplainerKey: "explainers.planning_long_term_harvest_shares",
    complexSidebarKey: "commissioning.harvest_shares_veg",
    // Veg-qualified so it never reads as a bare "Langzeit-Planung" next to the
    // fruit long-term link when veg + fruit are separate.
    longTermSidebarKey: "commissioning.planning_longterm_harvest_shares_veg_only",
  },
  {
    shareOption: ShareTypeEnum.HARVEST_SHARE_FRUIT,
    slug: "harvest-shares-fruits-only",
    complexPageTitleKey: "commissioning.planning_harvest_shares_fruits_only",
    longTermPageTitleKey: "commissioning.planning_long_term_harvest_share_fruits",
    complexExplainerKey: "explainers.planning_harvest_shares",
    longTermExplainerKey: "explainers.planning_long_term_harvest_shares_fruits",
    complexSidebarKey: "commissioning.harvest_shares_fruits_only",
    longTermSidebarKey: "commissioning.planning_longterm_harvest_shares_fruits_only",
  },
  {
    shareOption: ShareTypeEnum.CHICKEN_SHARE,
    slug: "chicken-shares",
    complexPageTitleKey: "commissioning.planning_additional_chicken_shares",
    longTermPageTitleKey: "commissioning.planning_additional_chicken_shares",
    complexExplainerKey: "explainers.planning_harvest_shares",
    longTermExplainerKey: "explainers.planning_harvest_shares",
    complexSidebarKey: "commissioning.planning_additional_chicken_shares",
    longTermSidebarKey: "commissioning.planning_additional_chicken_shares",
  },
  {
    shareOption: ShareTypeEnum.HONEY_SHARE,
    slug: "honey-shares",
    complexPageTitleKey: "commissioning.planning_additional_honey_shares",
    longTermPageTitleKey: "commissioning.planning_additional_honey_shares",
    complexExplainerKey: "explainers.planning_harvest_shares",
    longTermExplainerKey: "explainers.planning_harvest_shares",
    complexSidebarKey: "commissioning.planning_additional_honey_shares",
    longTermSidebarKey: "commissioning.planning_additional_honey_shares",
  },
  {
    shareOption: ShareTypeEnum.OIL_SHARE,
    slug: "oil-shares",
    complexPageTitleKey: "commissioning.planning_additional_oil_shares",
    longTermPageTitleKey: "commissioning.planning_additional_oil_shares",
    complexExplainerKey: "explainers.planning_harvest_shares",
    longTermExplainerKey: "explainers.planning_harvest_shares",
    complexSidebarKey: "commissioning.planning_additional_oil_shares",
    longTermSidebarKey: "commissioning.planning_additional_oil_shares",
  },
  {
    shareOption: ShareTypeEnum.GRAIN_SHARE,
    slug: "grain-shares",
    complexPageTitleKey: "commissioning.planning_additional_grain_shares",
    longTermPageTitleKey: "commissioning.planning_additional_grain_shares",
    complexExplainerKey: "explainers.planning_harvest_shares",
    longTermExplainerKey: "explainers.planning_harvest_shares",
    complexSidebarKey: "commissioning.planning_additional_grain_shares",
    longTermSidebarKey: "commissioning.planning_additional_grain_shares",
  },
  {
    shareOption: ShareTypeEnum.BREAD_SHARE,
    slug: "bread-shares",
    complexPageTitleKey: "commissioning.planning_additional_bread_shares",
    longTermPageTitleKey: "commissioning.planning_additional_bread_shares",
    complexExplainerKey: "explainers.planning_harvest_shares",
    longTermExplainerKey: "explainers.planning_harvest_shares",
    complexSidebarKey: "commissioning.planning_additional_bread_shares",
    longTermSidebarKey: "commissioning.planning_additional_bread_shares",
  },
];

export const PLANNING_BY_SLUG: Map<string, PlanningShareOptionConfig> = new Map(
  PLANNING_SHARE_OPTIONS.map((c) => [c.slug, c]),
);

export const PLANNING_BY_OPTION: Map<string, PlanningShareOptionConfig> =
  new Map(PLANNING_SHARE_OPTIONS.map((c) => [c.shareOption, c]));

/**
 * The ShareType that governs an option's planning nature RIGHT NOW.
 *
 * There is at most one share type active on any given day per option (the
 * one-open-per-share_option constraint), but a query that includes future
 * share types (``include_future``) can return the current one AND a not-yet-
 * started successor. The CURRENTLY-ACTIVE one wins so a future share type's
 * ``needs_complex_planning`` / ``is_additional_share_type`` can't prematurely
 * change today's view; only in a gap (nothing active today) does the earliest
 * upcoming share type govern. ISO ``YYYY-MM-DD`` strings compare
 * chronologically, so plain string comparison is correct.
 */
export function governingShareType<
  T extends { valid_from?: string; valid_until?: string | null },
>(shareTypes: T[], today: string): T | undefined {
  const activeNow = shareTypes.find(
    (st) =>
      (st.valid_from ?? "") <= today &&
      (st.valid_until == null || st.valid_until >= today),
  );
  if (activeNow) return activeNow;
  return [...shareTypes]
    .filter((st) => (st.valid_from ?? "") > today)
    .sort((a, b) => (a.valid_from ?? "").localeCompare(b.valid_from ?? ""))[0];
}
