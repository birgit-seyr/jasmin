import {
  CheckCircleOutlined,
  DownOutlined,
  EditOutlined,
  PauseCircleOutlined,
  UpOutlined,
} from "@ant-design/icons";
import { Button, Card, Space, Switch, Tag, Timeline, Typography } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type {
  DeliveryExceptionGap,
  ShareDelivery,
} from "@shared/api/generated/models";
import { useDateFormat, useShareTypeVariationSizeOptions } from "@hooks/index";

const { Text } = Typography;

const PAGE_SIZE = 5;

interface UpcomingDeliveriesCardProps {
  shareDeliveries: ShareDelivery[];
  /** Weeks a subscription would deliver but doesn't (delivery exception /
   *  Lieferpause) — no ShareDelivery row exists, so they're passed in and
   *  interleaved as greyed "paused" rows. */
  exceptionGaps?: DeliveryExceptionGap[];
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
  exceptionGaps = [],
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

  // Exception gaps that fall WITHIN the visible delivery window, deduped by
  // (year, week, share type, size). Pagination stays delivery-driven; gaps just
  // fill the paused weeks between the shown deliveries.
  const visibleGaps = useMemo(() => {
    if (exceptionGaps.length === 0 || visibleDeliveries.length === 0) return [];
    const yw = (year: number, week: number) => year * 100 + week;
    const first = visibleDeliveries[0];
    const last = visibleDeliveries[visibleDeliveries.length - 1];
    const lo = yw(first.year ?? 0, first.delivery_week ?? 0);
    const hi = yw(last.year ?? 0, last.delivery_week ?? 0);
    const seen = new Set<string>();
    return exceptionGaps.filter((gap) => {
      const key = yw(gap.year, gap.delivery_week);
      if (key < lo || key > hi) return false;
      const dedup = `${gap.year}-${gap.delivery_week}-${gap.share_type_name}-${gap.share_type_variation_size}`;
      if (seen.has(dedup)) return false;
      seen.add(dedup);
      return true;
    });
  }, [exceptionGaps, visibleDeliveries]);

  const timelineItems = useMemo(() => {
    // Merge real deliveries + exception-gap rows into one (year, week)-sorted
    // list so a paused week sits chronologically between the deliveries around
    // it. A gap carries no ShareDelivery, so it renders a compact "paused" row.
    type Row =
      | { sortKey: number; year: number; week: number; delivery: ShareDelivery }
      | {
          sortKey: number;
          year: number;
          week: number;
          gap: DeliveryExceptionGap;
        };
    const yw = (year: number, week: number) => year * 100 + week;
    const rows: Row[] = [
      ...visibleDeliveries.map((delivery) => ({
        sortKey: yw(delivery.year ?? 0, delivery.delivery_week ?? 0),
        year: delivery.year ?? 0,
        week: delivery.delivery_week ?? 0,
        delivery,
      })),
      ...visibleGaps.map((gap) => ({
        sortKey: yw(gap.year, gap.delivery_week),
        year: gap.year,
        week: gap.delivery_week,
        gap,
      })),
    ].sort((a, b) => a.sortKey - b.sortKey);

    return rows.map((row, index) => {
      // Hairline only at WEEK boundaries — consecutive rows in the same ISO
      // week stay grouped as one block.
      const next = rows[index + 1];
      const isWeekBoundary =
        next !== undefined && (next.year !== row.year || next.week !== row.week);
      const { year, week } = row;
      const isCurrentWeek = year === currentYear && week === currentWeek;
      const isPast =
        year < currentYear || (year === currentYear && week < currentWeek);

      if ("gap" in row) {
        const gap = row.gap;
        return {
          key: `gap-${gap.year}-${gap.delivery_week}-${gap.share_type_name}-${gap.share_type_variation_size}`,
          color: "gray" as const,
          dot: <PauseCircleOutlined />,
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
                <Text style={{ color: "var(--color-text-tertiary)" }}>
                  {t("commissioning.KW")} {gap.delivery_week}/{gap.year}
                  <Tag color="default" style={{ marginLeft: "8px" }}>
                    {t("members.delivery_paused")}
                  </Tag>
                </Text>
              </Space>
              <br />
              <Text type="secondary">
                {gap.share_type_name}{" "}
                {getShareTypeVariationSizeLabel(gap.share_type_variation_size)}
                {gap.note ? ` — ${gap.note}` : ""}
              </Text>
            </div>
          ),
        };
      }

      const delivery = row.delivery;
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
    visibleGaps,
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
