import { DeliveryStationDaySelector } from "@/features/commissioning/selectors";
import { ExplainerText } from "@shared/ui";
import { useTranslation } from "react-i18next";
import { useState } from "react";

export default function AbosEmails() {
  const { t } = useTranslation();
  const [selectedDeliveryStationDay, setSelectedDeliveryStationDay] = useState<
    string | null
  >(null);

  return (
    <div>
      <h1>{t("abos.emails")}</h1>
      <h3>{t("abos.delivery_station_days_emails")}</h3>
      <div style={{ marginLeft: "-2em" }}>
        <DeliveryStationDaySelector
          selectedDeliveryStationDay={selectedDeliveryStationDay}
          setSelectedDeliveryStationDay={setSelectedDeliveryStationDay}
        />
      </div>
      <h3>{t("abos.share_type_emails")}</h3>
      <h3>{t("abos.active_subscriptions_date_range_emails")}</h3>
      <ExplainerText title={t("common.info")}>
        {t("explainers.abos_emails")}
      </ExplainerText>
    </div>
  );
}
