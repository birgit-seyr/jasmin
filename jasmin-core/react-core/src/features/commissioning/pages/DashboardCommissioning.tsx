import { HeartOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";

import { ExplainerText } from "@shared/ui";

const DashboardCommissioning = () => {
  const { t } = useTranslation();
  return (
    <div>
      <HeartOutlined />
      <ExplainerText title={t("common.info")}>
        {t("explainers.dashboard_commissioning")}
      </ExplainerText>
    </div>
  );
};

export default DashboardCommissioning;
