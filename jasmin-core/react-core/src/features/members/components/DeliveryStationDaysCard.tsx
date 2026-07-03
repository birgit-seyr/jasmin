import { EnvironmentOutlined } from "@ant-design/icons";
import { Button, Card, Empty, Space } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCommissioningDeliveryStationsDaysList } from "@shared/api/generated/commissioning/commissioning";
import type { DeliveryStationDay } from "@shared/api/generated/models";
import { formatStationDayLabel } from "@shared/utils/stationDayLabel";
import DeliveryStationMemberModal from "../modals/DeliveryStationMemberModal";

interface DeliveryStationDaysCardProps {
  memberId: string;
}

// Prefer the currently-open row (valid_until null); otherwise the later-starting
// one. Used to collapse succeeded/duplicate rows for the same station+weekday.
const isMoreCurrent = (a: DeliveryStationDay, b: DeliveryStationDay) => {
  const aOpen = a.valid_until == null;
  const bOpen = b.valid_until == null;
  if (aOpen !== bOpen) return aOpen;
  return (a.valid_from ?? "") > (b.valid_from ?? "");
};

/** MemberDetail card listing the member's active / upcoming delivery station-days
 * (station × weekday, resolved server-side from their confirmed subscriptions'
 * default_delivery_station_day). Click a row → full station info + pickup + map. */
export default function DeliveryStationDaysCard({
  memberId,
}: DeliveryStationDaysCardProps) {
  const { t } = useTranslation();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data: stationDays } = useCommissioningDeliveryStationsDaysList(
    { member: memberId },
    { query: { enabled: !!memberId } },
  );

  // A member's subscription may reference an older (succeeded) station-day row
  // while an upcoming delivery uses the current one for the SAME station +
  // weekday — both carry the same label and would show as a duplicate. Collapse
  // to one row per (station, weekday), keeping the most current row.
  const rows = useMemo(() => {
    const byStationWeekday = new Map<string, DeliveryStationDay>();
    for (const stationDay of stationDays ?? []) {
      const key = `${stationDay.delivery_station}|${stationDay.delivery_day_number}`;
      const existing = byStationWeekday.get(key);
      if (!existing || isMoreCurrent(stationDay, existing)) {
        byStationWeekday.set(key, stationDay);
      }
    }
    return [...byStationWeekday.values()];
  }, [stationDays]);

  return (
    <Card
      title={
        <Space>
          <EnvironmentOutlined />
          {t("members.my_delivery_stations")}
        </Space>
      }
      className="member-card member-card--blue-title"
      style={{ marginTop: 16 }}
      styles={{ body: { padding: "12px 16px" } }}
    >
      {rows.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("members.no_delivery_stations")}
        />
      ) : (
        <Space direction="vertical" size={4} className="w-full">
          {rows.map((stationDay) => (
            <Button
              key={stationDay.id}
              type="link"
              icon={<EnvironmentOutlined />}
              style={{ paddingLeft: 0, textAlign: "left" }}
              onClick={() => setSelectedId(stationDay.id ?? null)}
            >
              {formatStationDayLabel(t, stationDay)}
            </Button>
          ))}
        </Space>
      )}

      <DeliveryStationMemberModal
        stationDayId={selectedId}
        onClose={() => setSelectedId(null)}
      />
    </Card>
  );
}
