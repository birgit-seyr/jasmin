import { Spin } from "antd";
import dayjs from "dayjs";
import { toApiDate } from "@shared/utils";
import { useTranslation } from "react-i18next";
import { Navigate, useParams } from "react-router-dom";
import { useShareTypes } from "@hooks/index";
import {
  governingShareType,
  PLANNING_BY_SLUG,
  type PlanningMode,
} from "@shared/planning/planningShareOptions";
import PlanningShareContentBase from "./PlanningShareContentBase";
import PlanningShareContentLongTermBase from "./PlanningShareContentLongTermBase";

interface PlanningShareContentPageProps {
  /** Which view this route renders. A ``complex`` route for an option whose
   *  active ShareType is NOT complex-planned falls back to the long-term view
   *  (there is no complex plan to show). */
  mode: PlanningMode;
}

/**
 * One data-driven planning page for every share option. The concrete view is
 * derived from the option's currently-active ``ShareType``:
 *
 *   - ``mode="complex"`` + ``needs_complex_planning`` → the per-week planner
 *     ({@link PlanningShareContentBase}).
 *   - otherwise → the long-term planner
 *     ({@link PlanningShareContentLongTermBase}).
 *
 * ``genericArticleColumn`` (the "Artikel" vs "Gemüse/Obst" column) comes from
 * ``is_additional_share_type``. Config (slug + i18n keys) lives in
 * ``@shared/planning/planningShareOptions``.
 */
export default function PlanningShareContentPage({
  mode,
}: PlanningShareContentPageProps) {
  const { t } = useTranslation();
  const { slug = "" } = useParams();
  const config = PLANNING_BY_SLUG.get(slug);

  const { shareTypes, loading } = useShareTypes(
    config
      ? {
          share_option: config.shareOption,
          active_at_date: toApiDate(dayjs())!,
          // Include a not-yet-started (future valid_from) share type so a
          // complex option in the gap before its season starts still resolves
          // as complex instead of silently degrading to the long-term view.
          include_future: true,
        }
      : { share_option: undefined },
  );

  if (!config) {
    // Unknown slug → back to the first planning page.
    return <Navigate to="/commissioning/planning/harvest-shares" replace />;
  }

  if (loading) {
    return <Spin />;
  }

  // Derive from the ShareType that governs TODAY (the currently-active one, or
  // the upcoming one in a gap) — NOT any future successor. The model default is
  // complex, so an unknown/absent share type keeps the complex route working.
  const governing = governingShareType(
    shareTypes,
    dayjs().format("YYYY-MM-DD"),
  );
  const needsComplexPlanning = governing
    ? (governing.needs_complex_planning ?? true)
    : true;
  const isAdditional = governing?.is_additional_share_type ?? false;

  const effectiveMode: PlanningMode =
    mode === "complex" && needsComplexPlanning ? "complex" : "long-term";

  const Base =
    effectiveMode === "complex"
      ? PlanningShareContentBase
      : PlanningShareContentLongTermBase;

  const shareArticleFilters: Record<string, boolean> =
    effectiveMode === "complex"
      ? { is_active: true, get_price_info: true }
      : { is_active: true };

  const pageTitleKey =
    effectiveMode === "complex"
      ? config.complexPageTitleKey
      : config.longTermPageTitleKey;
  const explainerKey =
    effectiveMode === "complex"
      ? config.complexExplainerKey
      : config.longTermExplainerKey;

  return (
    <Base
      shareOption={config.shareOption}
      shareArticleFilters={shareArticleFilters}
      pageTitle={t(pageTitleKey)}
      explainerKey={explainerKey}
      genericArticleColumn={isAdditional}
    />
  );
}
