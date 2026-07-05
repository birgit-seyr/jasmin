import {
  CalendarOutlined,
  ClockCircleOutlined,
  EnvironmentOutlined,
  MessageOutlined,
  PhoneOutlined,
  UserOutlined,
} from "@ant-design/icons";
import {
  useCommissioningDeliveryStationsDaysRetrieve,
  useCommissioningDeliveryStationsRetrieve,
} from "@shared/api/generated/commissioning/commissioning";
import { DeliveryStationMap } from "@shared/ui";
import {
  formatStationDayLabel,
  weekdayLabel,
} from "@shared/utils/stationDayLabel";
import { Descriptions, Image, Modal, Space, Spin, Typography } from "antd";
import DOMPurify from "dompurify";
import { useTranslation } from "react-i18next";

const { Link } = Typography;

interface DeliveryStationMemberModalProps {
  /** The station-day to show. ``null`` closes the modal. The rich station data
   *  (picture / messenger / contact) is fetched from its ``delivery_station``. */
  stationDayId: string | null;
  onClose: () => void;
}

const hourMinute = (value?: string | null) => (value ? value.slice(0, 5) : "");

/** Read-only member-facing view of a delivery station-day: the pickup weekday +
 * times from the station-day, and the station's photo / address / access /
 * contact / messenger group / map. Both are fetched by id when opened. */
export default function DeliveryStationMemberModal({
  stationDayId,
  onClose,
}: DeliveryStationMemberModalProps) {
  const { t } = useTranslation();

  const { data: stationDay, isLoading: dayLoading } =
    useCommissioningDeliveryStationsDaysRetrieve(stationDayId ?? "", {
      query: { enabled: !!stationDayId },
    });
  const stationId = stationDay?.delivery_station ?? null;
  const { data: station } = useCommissioningDeliveryStationsRetrieve(
    stationId ?? "",
    { query: { enabled: !!stationId } },
  );

  const rawLat = station?.coords_lat ?? stationDay?.coords_lat;
  const rawLon = station?.coords_lon ?? stationDay?.coords_lon;
  const lat = Number(rawLat);
  const lon = Number(rawLon);
  // ``Number(null)`` / ``Number("")`` are 0 (finite), so an un-geocoded station
  // would otherwise pin the map at (0,0) "Null Island". Require non-empty raw
  // values and exclude the exact 0/0 placeholder.
  const hasCoords =
    !!rawLat &&
    !!rawLon &&
    Number.isFinite(lat) &&
    Number.isFinite(lon) &&
    (lat !== 0 || lon !== 0);
  const pictureSrc = station?.picture || station?.photo_link || undefined;
  const addressLine = station
    ? [
        station.address,
        [station.zip_code, station.city].filter(Boolean).join(" "),
      ]
        .filter(Boolean)
        .join(", ")
    : "";
  const pickup =
    stationDay?.pickup_time_begin || stationDay?.pickup_time_end
      ? `${hourMinute(stationDay?.pickup_time_begin)}–${hourMinute(stationDay?.pickup_time_end)}`
      : "";

  return (
    <Modal
      open={!!stationDayId}
      onCancel={onClose}
      onOk={onClose}
      footer={null}
      width={560}
      title={
        <Space>
          <EnvironmentOutlined />
          {stationDay
            ? formatStationDayLabel(t, stationDay)
            : t("members.delivery_station")}
        </Space>
      }
    >
      {dayLoading || !stationDay ? (
        <Spin />
      ) : (
        <Space direction="vertical" size={12} className="w-full">
          {pictureSrc && (
            <Image
              src={pictureSrc}
              alt={stationDay.delivery_station_short_name ?? ""}
              style={{ maxHeight: 200, objectFit: "cover" }}
            />
          )}
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item
              label={
                <Space size={4}>{t("delivery_stations.pickup_day")}</Space>
              }
            >
              {weekdayLabel(t, stationDay.delivery_day_number)}
            </Descriptions.Item>

            <Descriptions.Item
              label={
                <Space size={4}>{t("delivery_stations.pickup_times")}</Space>
              }
            >
              {pickup}
            </Descriptions.Item>

            <Descriptions.Item
              label={
                <Space size={4}>
                  {t("delivery_stations.special_instructions")}
                </Space>
              }
            >
              {stationDay.special_instructions ? (
                <span
                  dangerouslySetInnerHTML={{
                    __html: DOMPurify.sanitize(stationDay.special_instructions),
                  }}
                />
              ) : null}
            </Descriptions.Item>

            <Descriptions.Item label={t("delivery_stations.address")}>
              {addressLine}
            </Descriptions.Item>

            <Descriptions.Item label={t("delivery_stations.info")}>
              {station?.info ? (
                <span
                  dangerouslySetInnerHTML={{
                    __html: DOMPurify.sanitize(station.info),
                  }}
                />
              ) : null}
            </Descriptions.Item>

            <Descriptions.Item
              label={
                <Space size={4}>{t("delivery_stations.access_code")}</Space>
              }
            >
              {station?.access_code}
            </Descriptions.Item>

            <Descriptions.Item
              label={
                <Space size={4}>
                  <UserOutlined />
                  {t("delivery_stations.contact_name")}
                </Space>
              }
            >
              {station?.contact_name}
            </Descriptions.Item>

            <Descriptions.Item
              label={
                <Space size={4}>
                  <PhoneOutlined />
                  {t("delivery_stations.phone")}
                </Space>
              }
            >
              {station?.contact_phone}
            </Descriptions.Item>

            {station?.messenger_group_link && (
              <Descriptions.Item
                label={
                  <Space size={4}>
                    <MessageOutlined />
                    {t("delivery_stations.messenger_group_link")}
                  </Space>
                }
              >
                <Link
                  href={station.messenger_group_link}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t("delivery_stations.messenger_open")}
                </Link>
              </Descriptions.Item>
            )}
          </Descriptions>

          {hasCoords && (
            <DeliveryStationMap
              markers={[
                {
                  id: stationId ?? "station",
                  lat,
                  lon,
                  label: stationDay.delivery_station_short_name ?? "",
                },
              ]}
              height={260}
            />
          )}
        </Space>
      )}
    </Modal>
  );
}
