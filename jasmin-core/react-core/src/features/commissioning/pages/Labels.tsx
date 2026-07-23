import { useTranslation } from "react-i18next";

import { ExplainerText } from "@shared/ui";

export default function Labels() {
  const { t } = useTranslation();

  return (
    <div>
      coming soon ...
      <ExplainerText title={t("common.info")}>
        {t("explainers.labels_page")}
      </ExplainerText>
    </div>
  );
}
