import { useTranslation } from "react-i18next";
import { ShareTypeEnum } from "@shared/api/generated/models";
import PlanningAdditionalSharesBase from "./PlanningShareContentBaseAdditionalShares";

export default function PlanningShareContentCHICKENSHARE() {
  const { t } = useTranslation();
  return (
    <PlanningAdditionalSharesBase
      shareOption={ShareTypeEnum.CHICKEN_SHARE}
      pageTitle={t("commissioning.planning_additional_chicken_shares")}
      explainerKey="explainers.planning_harvest_shares"
    />
  );
}
