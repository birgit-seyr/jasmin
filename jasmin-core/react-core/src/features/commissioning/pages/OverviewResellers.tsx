import { useTranslation } from "react-i18next";

import { ExplainerText } from "@shared/ui";

export default function OverviewResellers() {
  const { t } = useTranslation();

  return (
    <div>
      <h1>OverviewResellers</h1>
      <p>OverviewResellers page content coming soon...</p>
      <ExplainerText title={t("common.info")}>
        {t("explainers.overview_resellers")}
      </ExplainerText>
    </div>
  );
}
