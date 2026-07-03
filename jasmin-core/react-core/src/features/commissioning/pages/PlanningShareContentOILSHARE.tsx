import { useTranslation } from "react-i18next";
import { ShareTypeEnum } from "@shared/api/generated/models";
import PlanningAdditionalSharesBase from "./PlanningShareContentBaseAdditionalShares";

export default function PlanningShareContentOILSHARE() {
  const { t } = useTranslation();
  return (
    <PlanningAdditionalSharesBase
      shareOption={ShareTypeEnum.OIL_SHARE}
      pageTitle={t("commissioning.planning_additional_oil_shares")}
      explainerKey="explainers.planning_harvest_shares"
    />
  );
}
