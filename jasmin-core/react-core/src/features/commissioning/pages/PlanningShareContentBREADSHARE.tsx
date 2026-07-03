import { useTranslation } from "react-i18next";
import { ShareTypeEnum } from "@shared/api/generated/models";
import PlanningAdditionalSharesBase from "./PlanningShareContentBaseAdditionalShares";

export default function PlanningShareContentBREADSHARE() {
  const { t } = useTranslation();
  return (
    <PlanningAdditionalSharesBase
      shareOption={ShareTypeEnum.BREAD_SHARE}
      pageTitle={t("commissioning.planning_additional_bread_shares")}
      explainerKey="explainers.planning_harvest_shares"
    />
  );
}
