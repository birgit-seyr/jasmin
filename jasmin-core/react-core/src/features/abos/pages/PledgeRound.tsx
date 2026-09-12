import { useTranslation } from "react-i18next";

import { ExplainerText } from "@shared/ui";

const PledgeRound = () => {
  const { t } = useTranslation();

  return (
    <div>
      <h1>Pledge Round</h1>
      <p>Pledge Round page content coming soon...</p>
      <ExplainerText title={t("common.info")}>
        {t("explainers.pledge_round")}
      </ExplainerText>
    </div>
  );
};

export default PledgeRound;
