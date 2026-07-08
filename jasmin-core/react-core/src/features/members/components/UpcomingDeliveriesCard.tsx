import {
  CheckCircleOutlined,
  DownOutlined,
  EditOutlined,
  UpOutlined,
} from "@ant-design/icons";
import { Button, Card, Space, Switch, Tag, Timeline, Typography } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ShareDelivery } from "@shared/api/generated/models";
import { useDateFormat, useShareTypeVariationSizeOptions } from "@hooks/index";

const { Text } = Typography;

const PAGE_SIZE = 5;

interface UpcomingDeliveriesCardProps {
  shareDeliveries: ShareDelivery[];
  currentWeek: number;
  currentYear: number;
  weekdayChoices: { value: number; label: string }[];
  onEditDelivery: (delivery: ShareDelivery) => void;
  /** On-off opt-in toggle for ``requires_optin`` deliveries. Omit to hide
   *  the toggle (e.g. read-only contexts). */
  onToggleOptin?: (delivery: ShareDelivery, optIn: boolean) => void;
  /** Id of the delivery whose opt-in toggle is mid-flight (spinner). */
  togglingOptinId?: string | null;
}

const UpcomingDeliveriesCard = ({
  shareDeliveries,
  currentWeek,
  currentYear,
  weekdayChoices,
  onEditDelivery,
  onToggleOptin,
  togglingOptinId,
}: UpcomingDeliveriesCardProps) => {
  const { t } = useTranslation();
  const { formatDate } = useDateFormat();
  const [futureCount, setFutureCount] = useState(PAGE_SIZE);
  const [pastCount, setPastCount] = useState(0);
  const { getShareTypeVariationSizeLabel } = useShareTypeVariationSizeOptions();

  const getWeekdayLabel = useCallback(
    (dayNumber: number) => {
      const weekday = weekdayChoices.find((day) => day.value === dayNumber);
      return weekday ? weekday.label : "";
    },
    [weekdayChoices],
  );

  const getDeliveryDate = useCallback(
    (year: number, week: number, dayNumber: number) => {
      return (
        formatDate(
          dayjs()
            .year(year)
            .isoWeek(week)
            .startOf("isoWeek")
            .add(dayNumber, "day"),
        ) ?? ""
      );
    },
    [formatDate],
  );

  const { pastDeliveries, futureDeliveries } = useMemo(() => {
    const seen = new Set<string>();
    const sorted = [...shareDeliveries]
      .sort((a, b) => {
        const yearA = a.year ?? 0;
        const yearB = b.year ?? 0;
        if (yearA !== yearB) return yearA - yearB;
        return (a.delivery_week ?? 0) - (b.delivery_week ?? 0);
      })
      .filter((delivery) => {
        const shareTypeName =
          delivery.ordered_share_type_name ?? delivery.share_type_name ?? "";
        const orderedSize =
          delivery.ordered_variation_name ??
          delivery.share_type_variation_size ??
          "";
        const key = `${delivery.year}-${delivery.delivery_week}-${shareTypeName}-${orderedSize}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });

    const past: ShareDelivery[] = [];
    const future: ShareDelivery[] = [];

    for (const delivery of sorted) {
      const year = delivery.year ?? 0;
      const week = delivery.delivery_week ?? 0;
      const isPast =
        year < currentYear ||
        (year === currentYear && week < currentWeek);
      if (isPast) past.push(delivery);
      else future.push(delivery);
    }

    return { pastDeliveries: past, futureDeliveries: future };
  }, [shareDeliveries, currentYear, currentWeek]);

  const visibleDeliveries = useMemo(() => {
    const visiblePast =
      pastCount > 0
        ? pastDeliveries.slice(Math.max(0, pastDeliveries.length - pastCount))
        : [];
    const visibleFuture = futureDeliveries.slice(0, futureCount);
    return [...visiblePast, ...visibleFuture];
  }, [pastDeliveries, futureDeliveries, pastCount, futureCount]);
  const hasMorePast = pastCount < pastDeliveries.length;
  const hasMoreFuture = futureCount < futureDeliveries.length;

  const timelineItems = useMemo(() => {
    return visibleDeliveries.map((delivery, index) => {
      // Hairline only at WEEK boundaries — consecutive deliveries in the same
      // ISO week stay grouped as one block (no separator between them), so two
      // deliveries in the same week read as a pair. (List is year/week-sorted,
      // so same-week rows are always adjacent.)
      const nextDelivery = visibleDeliveries[index + 1];
      const isWeekBoundary =
        nextDelivery !== undefined &&
        (nextDelivery.year !== delivery.year ||
          nextDelivery.delivery_week !== delivery.delivery_week);
      const year = delivery.year ?? 0;
      const week = delivery.delivery_week ?? 0;
      const isCurrentWeek = year === currentYear && week === currentWeek;
      const isPast =
        year < currentYear || (year === currentYear && week < currentWeek);
      const deliveryDate =
        delivery.delivery_day_number !== undefined &&
        delivery.year !== undefined &&
        delivery.delivery_week !== undefined
          ? getDeliveryDate(
              delivery.year,
              delivery.delivery_week,
              delivery.delivery_day_number,
            )
          : null;

      return {
        key: `${delivery.year}-${delivery.delivery_week}-${delivery.id}`,
        color: isCurrentWeek ? "green" : isPast ? "gray" : ("blue" as const),
        dot: isCurrentWeek ? <CheckCircleOutlined /> : null,
        children: (
          <div
            style={{
              paddingBottom: isWeekBoundary ? 12 : 0,
              borderBottom: isWeekBoundary
                ? "1px solid var(--color-border-subtle)"
                : undefined,
            }}
          >
            <Space>
              <Text
                strong
                style={
                  isPast ? { color: "var(--color-text-tertiary)" } : undefined
                }
              >
                {t("commissioning.KW")} {delivery.delivery_week}/{delivery.year}
                {isCurrentWeek && (
                  <Tag color="green" style={{ marginLeft: "8px" }}>
                    {t("members.current_week")}
                  </Tag>
                )}
              </Text>
              {!isPast && !isCurrentWeek && (
                <Button
                  type="link"
                  size="small"
                  icon={<EditOutlined />}
                  onClick={() => onEditDelivery(delivery)}
                  aria-label={t("members.edit_delivery")}
                />
              )}
              {delivery.requires_optin && onToggleOptin && (
                <Space size={4}>
                  <Switch
                    size="small"
                    checked={Boolean(delivery.is_opted_in)}
                    disabled={Boolean(delivery.optin_locked) || isPast}
                    loading={togglingOptinId === delivery.id}
                    onChange={(checked) => onToggleOptin(delivery, checked)}
                    aria-label={t("members.optin_toggle")}
                  />
                  <Text type="secondary" style={{ fontSize: "0.8em" }}>
                    {Boolean(delivery.optin_locked) || isPast
                      ? delivery.is_opted_in
                        ? t("members.optin_confirmed")
                        : t("members.optin_skipped")
                      : delivery.optin_deadline
                        ? t("members.optin_deadline_label", {
                            date: formatDate(delivery.optin_deadline),
                          })
                        : t("members.optin_toggle")}
                  </Text>
                </Space>
              )}
            </Space>
            <br />
            <Text type="secondary">
              {delivery.ordered_share_type_name ??
                delivery.share_type_name ??
                ""}{" "}
              {getShareTypeVariationSizeLabel(
                delivery.ordered_variation_name ??
                  delivery.share_type_variation_size ??
                  "",
              )}
              {deliveryDate && (
                <>
                  {" - "}
                  <Text type="secondary" strong>
                    {deliveryDate}
                  </Text>
                  {delivery.delivery_day_number !== undefined && (
                    <> ({getWeekdayLabel(delivery.delivery_day_number)})</>
                  )}
                </>
              )}
              {" - "}
              {delivery.delivery_station_name}{" "}
              {delivery.joker_taken && (
                <Tag
                  color="darkorange"
                  style={{ marginTop: "4px", marginLeft: "2px" }}
                >
                  Joker
                </Tag>
              )}
              {delivery.donation_joker_taken && (
                <Tag
                  color="darkorange"
                  style={{ marginTop: "4px", marginLeft: "2px" }}
                >
                  {t("members.donation_joker_tag")}
                </Tag>
              )}
            </Text>
          </div>
        ),
      };
    });
  }, [
    visibleDeliveries,
    currentYear,
    currentWeek,
    t,
    getShareTypeVariationSizeLabel,
    getWeekdayLabel,
    getDeliveryDate,
    formatDate,
    onEditDelivery,
    onToggleOptin,
    togglingOptinId,
  ]);

  return (
    <Card
      title={t("members.deliveries")}
      className="member-card green-border member-card--blue-title"
      style={{ marginBottom: 0 }}
    >
      {hasMorePast && (
        <div style={{ textAlign: "center", marginBottom: 8 }}>
          <Button
            type="link"
            icon={<UpOutlined />}
            onClick={() => setPastCount((c) => c + PAGE_SIZE)}
          >
            {t("common.load_more")}
          </Button>
        </div>
      )}
      <Timeline items={timelineItems} />
      {hasMoreFuture && (
        <div className="text-center">
          <Button
            type="link"
            icon={<DownOutlined />}
            onClick={() => setFutureCount((c) => c + PAGE_SIZE)}
          >
            {t("common.load_more")}
          </Button>
        </div>
      )}
    </Card>
  );
};

export default UpcomingDeliveriesCard;
