import { HeartOutlined } from "@ant-design/icons";
import { Alert } from "antd";
import type { FC } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { useCrates } from "@features/commissioning/hooks";

const DashboardConfiguration: FC = () => {
  const { t } = useTranslation();
  // ``includeNullOption: false`` so ``crates`` counts only REAL crates — with the
  // default the list carries a synthetic "no crate" placeholder and is never
  // empty, which would defeat the "no crates yet" check below.
  const { crates, loading } = useCrates({ includeNullOption: false });

  return (
    <>
      <HeartOutlined />
      <h1>{t("configuration.dashboard_title")}</h1>
      {!loading && crates.length === 0 && (
        <Alert
          type="warning"
          showIcon
          className="page-narrow mb-1em"
          description={
            <>
              {t("configuration.first_step_crates_note")}{" "}
              <Link to="/commissioning/list-crates">
                {t("configuration.first_step_crates_link")}
              </Link>
            </>
          }
        />
      )}
      <div className="page-narrow">
        {t("configuration.dashboard_note")}
        {t("configuration.dashboard_note2")}
        <h3>{t("configuration.checkbox_note")}</h3>
      </div>
    </>
  );
};

export default DashboardConfiguration;
