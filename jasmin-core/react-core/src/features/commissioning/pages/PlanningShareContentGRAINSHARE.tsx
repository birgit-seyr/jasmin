import { useTranslation } from "react-i18next";
import { ShareTypeEnum } from "@shared/api/generated/models";
import PlanningAdditionalSharesBase from "./PlanningShareContentBaseAdditionalShares";

export default function PlanningShareContentGRAINSHARE() {
  const { t } = useTranslation();
  return (
    <PlanningAdditionalSharesBase
      shareOption={ShareTypeEnum.GRAIN_SHARE}
      pageTitle={t("commissioning.planning_additional_grain_shares")}
      explainerKey="explainers.planning_harvest_shares"
    />
  );
}
