import { useTranslation } from "react-i18next";
import { ShareTypeEnum } from "@shared/api/generated/models";
import PlanningAdditionalSharesBase from "./PlanningShareContentBaseAdditionalShares";

export default function PlanningShareContentHONEYSHARE() {
  const { t } = useTranslation();
  return (
    <PlanningAdditionalSharesBase
      shareOption={ShareTypeEnum.HONEY_SHARE}
      pageTitle={t("commissioning.planning_additional_honey_shares")}
      explainerKey="explainers.planning_harvest_shares"
    />
  );
}
