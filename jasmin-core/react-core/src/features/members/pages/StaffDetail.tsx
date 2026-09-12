import { useTranslation } from "react-i18next";

import { ExplainerText } from "@shared/ui";

const StaffDetail = () => {
  const { t } = useTranslation();

  return (
    <div>
      coming soon ...
      <ExplainerText title={t("common.info")}>
        {t("explainers.staff_detail")}
      </ExplainerText>
    </div>
  );
};

export default StaffDetail;
