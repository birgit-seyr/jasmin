import { Card, DatePicker, Spin, Typography } from "antd";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useCommissioningPurchaseCostByWeekList } from "@shared/api/generated/commissioning/commissioning";
import type { PurchaseCostByWeek } from "@shared/api/generated/models";
import { StatsBarChart } from "@shared/ui";
import {
  useCurrency,
  useDateFormat,
  useDateRangePresets,
  useFiscalYearRangeState,
} from "@hooks/index";

const { RangePicker } = DatePicker;
const { Text } = Typography;

// Finance-green — the same single-money-series colour DashboardAbos uses for
// billed income (this is spend, but the pages read as a matched pair).
const PURCHASE_COLOR = "#3f8600";

/**
 * Office overview of purchase ("Zukauf") spending: total money bought-in per
 * ISO week over a date range, as a bar per week. Mirrors DashboardAbos — a
 * fiscal-year RangePicker + a dark-green Card holding the chart. The figures
 * are the same per-week purchase totals shown on the harvest-share-planning
 * page, aggregated server-side (``purchase_cost_by_week``).
 */
export default function StatisticsPurchase() {
  const { t } = useTranslation();
  const { formatCurrency } = useCurrency();
  const { dateFormat, formatDateForAPI } = useDateFormat();
  const presets = useDateRangePresets();

  // Default window: the tenant's current fiscal year.
  const [range, setRange] = useFiscalYearRangeState();

  const params = useMemo(
    () => ({
      start_date: range ? (formatDateForAPI(range[0]) ?? "") : "",
      end_date: range ? (formatDateForAPI(range[1]) ?? "") : "",
    }),
    [range, formatDateForAPI],
  );

  // Gated on ``range`` so we never fire with empty date params.
  const { data: rawData, isLoading } = useCommissioningPurchaseCostByWeekList(
    params,
    { query: { enabled: !!range } },
  );

  const { chartData, series, total } = useMemo(() => {
    const points = (rawData ?? []) as PurchaseCostByWeek[];
    const chartData = points.map((point) => ({
      // Bare ISO week number on the x-axis (the selected range is shown in the
      // picker above); ``amount`` is a 2dp money string on the wire.
      label: point.week,
      amount: parseFloat(point.amount) || 0,
    }));
    const total = chartData.reduce((sum, point) => sum + point.amount, 0);
    const series = [
      {
        id: "amount",
        label: t("commissioning.statistics_purchase_series"),
        color: PURCHASE_COLOR,
      },
    ];
    return { chartData, series, total };
  }, [rawData, t]);

  return (
    <div>
      <h1>{t("commissioning.statistics_purchase")}</h1>

      <Spin spinning={isLoading}>
        <RangePicker
          value={range}
          onChange={(v) => setRange(v && v[0] && v[1] ? [v[0], v[1]] : null)}
          presets={presets}
          format={dateFormat}
          allowClear={false}
          aria-label={t("commissioning.statistics_purchase_date_range")}
        />

        {/* The totals are only as good as the prices entered in the planning /
            article-price screens — same data-quality caveat as the current-stock
            documentation page. */}
        <div
          className="alert-banner alert-banner-danger"
          style={{ marginTop: "1em" }}
        >
          {t("commissioning.statistics_purchase_data_quality_warning")}
        </div>

        <Card
          className="dark-green-border"
          title={t("commissioning.statistics_purchase_chart_title")}
          style={{ marginTop: "1em" }}
        >
          <Text type="secondary">
            {t("commissioning.statistics_purchase_total", {
              total: formatCurrency(total),
            })}
          </Text>
          <StatsBarChart
            data={chartData}
            series={series}
            height={320}
            emptyText={t("commissioning.statistics_purchase_no_data")}
            valueFormatter={formatCurrency}
            // Accessible name for the chart SVG + caption/header for its
            // visually-hidden data table (per-week figures for screen readers).
            ariaLabel={t("commissioning.statistics_purchase_chart_title")}
            xHeader={t("commissioning.KW")}
            // Weeks with no buy-in (e.g. delivery-exception weeks): a dark-grey
            // baseline stub bar, with their x-axis week number one step greyer.
            // Show every week number, not just recharts' auto-thinned subset.
            showEmptyBars
            muteEmptyLabels
            showAllXLabels
          />
        </Card>
      </Spin>
    </div>
  );
}
