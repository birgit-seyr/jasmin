import { Spin } from "antd";
import dayjs from "dayjs";
import { ShareTypeEnum } from "@shared/api/generated/models";
import { useShareTypes } from "@hooks/index";
import PlanningHarvestSharesBase from "./PlanningShareContentBase";
import PlanningLongTermHarvestSharesBase from "./PlanningShareContentLongTermBase";

interface PlanningAdditionalSharesBaseProps {
  shareOption: ShareTypeEnum;
  pageTitle: string;
  explainerKey: string;
  /** Extra article-list filters for the planning table (defaults to active +
   *  price info). The base also restricts articles to this ``shareOption``. */
  shareArticleFilters?: Record<string, boolean>;
}

/**
 * Dispatches an additional share option's planning page based on its
 * ``ShareType.needs_complex_planning`` flag (set in the ShareType table on
 * ConfigurationSubscriptions):
 *
 *   * ``true``  → the full per-week harvest-style planner
 *     ({@link PlanningHarvestSharesBase}) — the plan changes each week.
 *   * ``false`` → the long-term planner
 *     ({@link PlanningLongTermHarvestSharesBase}) — a constant plan set once
 *     and carried across the weeks (e.g. 1 jar of honey every delivery).
 *
 * Both bases are already parameterised by ``share_option``, so the same UI
 * serves any additional share option.
 */
export default function PlanningAdditionalSharesBase({
  shareOption,
  pageTitle,
  explainerKey,
  shareArticleFilters = { is_active: true, get_price_info: true },
}: PlanningAdditionalSharesBaseProps) {
  const { shareTypes, loading } = useShareTypes({
    share_option: shareOption,
    active_at_date: dayjs().format("YYYY-MM-DD"),
  });

  if (loading) {
    return <Spin />;
  }

  // Complex when any active ShareType for this option needs it (the model
  // default). Only when every share type is simple do we show the long-term UI.
  const needsComplexPlanning = shareTypes.some(
    (st) =>
      (st as { needs_complex_planning?: boolean }).needs_complex_planning ??
      true,
  );

  const Planner = needsComplexPlanning
    ? PlanningHarvestSharesBase
    : PlanningLongTermHarvestSharesBase;

  return (
    <Planner
      shareOption={shareOption}
      shareArticleFilters={shareArticleFilters}
      pageTitle={pageTitle}
      explainerKey={explainerKey}
      // Honey/chicken/… aren't "Gemüse / Obst" — title the column "Artikel".
      genericArticleColumn
    />
  );
}
