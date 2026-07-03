import { useTranslation } from "react-i18next";
import { ShareTypeEnum } from "@shared/api/generated/models";
import PlanningLongTermHarvestSharesBase from "./PlanningShareContentLongTermBase";

export default function PlanningLongTermHarvestShares() {
  const { t } = useTranslation();

  const shareOption = ShareTypeEnum.HARVEST_SHARE;

  const shareArticleFilters = {
    is_active: true,
  };

  return (
    <PlanningLongTermHarvestSharesBase
      shareOption={shareOption}
      shareArticleFilters={shareArticleFilters}
      pageTitle={t("commissioning.planning_long_term_harvest_share_vegs")}
      explainerKey="explainers.planning_long_term_harvest_shares"
    />
  );
}
