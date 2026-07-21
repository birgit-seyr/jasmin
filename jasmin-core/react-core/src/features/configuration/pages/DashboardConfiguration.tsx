import { HeartOutlined } from "@ant-design/icons";
import type { FC } from "react";
import { useTranslation } from "react-i18next";

const DashboardConfiguration: FC = () => {
  const { t } = useTranslation();

  return (
    <>
      <HeartOutlined />
      <h1>{t("configuration.dashboard_title")}</h1>

      <div className="page-narrow">
        {t("configuration.dashboard_note")}
        {t("configuration.dashboard_note2")}
        <h3>{t("configuration.checkbox_note")}</h3>
      </div>
    </>
  );
};

export default DashboardConfiguration;
