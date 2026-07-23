import { useTranslation } from "react-i18next";

import { ExplainerText } from "@shared/ui";

const ListMarkets = () => {
  const { t } = useTranslation();

  return (
    <div>
      <p>coming soon...</p>
      <ExplainerText title={t("common.info")}>
        {t("explainers.list_markets")}
      </ExplainerText>
    </div>
  );
};

export default ListMarkets;
