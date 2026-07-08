import { DeliveryStationDaySelector } from "@/features/commissioning/selectors";
import { ShareTypeSelector } from "@shared/selectors";
import { ExplainerText } from "@shared/ui";
import { Card, DatePicker, Flex, Typography } from "antd";
import type { Dayjs } from "dayjs";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useCommissioningSubscriptionMemberEmailsRetrieve } from "@shared/api/generated/commissioning/commissioning";
import { useDateFormat, useDateRangePresets } from "@hooks/index";
import CopyableEmailList from "@features/abos/components/CopyableEmailList";

const { RangePicker } = DatePicker;
const { Text } = Typography;

/**
 * Email distribution lists ("Emailverteiler"): copyable recipient lists built
 * by filtering active subscriptions — by delivery-station-day, by share type,
 * or by an active-in-date-range window. Each filter lives in its own card and
 * fetches the same ``subscription_member_emails`` endpoint.
 */
export default function AbosEmails() {
  const { t } = useTranslation();
  const { dateFormat, formatDateForAPI } = useDateFormat();
  const presets = useDateRangePresets();

  const [selectedDeliveryStationDay, setSelectedDeliveryStationDay] = useState<
    string | null
  >(null);
  const [selectedShareType, setSelectedShareType] = useState<string | null>(
    null,
  );
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null);

  const byStationDay = useCommissioningSubscriptionMemberEmailsRetrieve(
    { delivery_station_day: selectedDeliveryStationDay ?? "" },
    { query: { enabled: !!selectedDeliveryStationDay } },
  );

  const byShareType = useCommissioningSubscriptionMemberEmailsRetrieve(
    { share_type: selectedShareType ?? "" },
    { query: { enabled: !!selectedShareType } },
  );

  const byDateRange = useCommissioningSubscriptionMemberEmailsRetrieve(
    {
      date_from: range ? (formatDateForAPI(range[0]) ?? "") : "",
      date_to: range ? (formatDateForAPI(range[1]) ?? "") : "",
    },
    { query: { enabled: !!range } },
  );

  return (
    <div>
      <h1>{t("abos.emails")}</h1>
      <div style={{ marginBottom: "2em" }}>
        <Card
          className="dark-green-border"
          title={t("abos.delivery_station_days_emails")}
          style={{ marginTop: "1.5em" }}
        >
          <Flex vertical gap="middle" align="start">
            <Text type="secondary">{t("abos.emails_by_station_hint")}</Text>
            <DeliveryStationDaySelector
              selectedDeliveryStationDay={selectedDeliveryStationDay}
              setSelectedDeliveryStationDay={setSelectedDeliveryStationDay}
            />
            <CopyableEmailList
              data={byStationDay.data}
              loading={byStationDay.isFetching}
              enabled={!!selectedDeliveryStationDay}
            />
          </Flex>
        </Card>

        <Card
          className="dark-green-border"
          title={t("abos.share_type_emails")}
          style={{ marginTop: "1.5em" }}
        >
          <Flex vertical gap="middle" align="start">
            <Text type="secondary">{t("abos.emails_by_share_type_hint")}</Text>
            <ShareTypeSelector
              selectedShareType={selectedShareType}
              setSelectedShareType={(v) => setSelectedShareType(v)}
              style={{ marginLeft: "-1em" }}
            />
            <CopyableEmailList
              data={byShareType.data}
              loading={byShareType.isFetching}
              enabled={!!selectedShareType}
            />
          </Flex>
        </Card>

        <Card
          className="dark-green-border"
          title={t("abos.active_subscriptions_date_range_emails")}
          style={{ marginTop: "1.5em" }}
        >
          <Flex vertical gap="middle" align="start">
            <Text type="secondary">{t("abos.emails_by_date_range_hint")}</Text>
            <RangePicker
              value={range}
              onChange={(v) =>
                setRange(v && v[0] && v[1] ? [v[0], v[1]] : null)
              }
              presets={presets}
              format={dateFormat}
            />
            <CopyableEmailList
              data={byDateRange.data}
              loading={byDateRange.isFetching}
              enabled={!!range}
            />
          </Flex>
        </Card>
      </div>
      <ExplainerText title={t("common.info")} marginTop="0">
        {t("explainers.abos_emails")}
      </ExplainerText>
    </div>
  );
}
