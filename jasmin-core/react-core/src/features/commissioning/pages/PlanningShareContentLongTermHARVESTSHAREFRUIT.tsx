import { useTranslation } from "react-i18next";
import { ShareTypeEnum } from "@shared/api/generated/models";
import PlanningLongTermHarvestSharesBase from "./PlanningShareContentLongTermBase";

export default function PlanningLongTermHarvestSharesFruits() {
  const { t } = useTranslation();

  const shareOption = ShareTypeEnum.HARVEST_SHARE_FRUIT;

  const shareArticleFilters = {
    is_active: true,
  };

  return (
    <PlanningLongTermHarvestSharesBase
      shareOption={shareOption}
      shareArticleFilters={shareArticleFilters}
      pageTitle={t("commissioning.planning_long_term_harvest_share_fruits")}
      explainerKey="explainers.planning_long_term_harvest_shares_fruits"
    />
  );
}
