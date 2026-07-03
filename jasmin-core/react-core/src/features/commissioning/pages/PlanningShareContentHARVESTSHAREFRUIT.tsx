import { useTranslation } from "react-i18next";
import { ShareTypeEnum } from "@shared/api/generated/models";
import PlanningHarvestSharesBase from "./PlanningShareContentBase";

export default function PlanningHarvestSharesFruits() {
  const { t } = useTranslation();

  const shareOption = ShareTypeEnum.HARVEST_SHARE_FRUIT;

  const shareArticleFilters = {
    is_active: true,
    get_price_info: true,
  };

  return (
    <PlanningHarvestSharesBase
      shareOption={shareOption}
      shareArticleFilters={shareArticleFilters}
      pageTitle={t("commissioning.planning_harvest_shares_fruits_only")}
      explainerKey="explainers.planning_harvest_shares"
    />
  );
}
