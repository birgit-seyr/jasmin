import { Card, DatePicker, Divider, Spin, Table, Typography } from "antd";
import dayjs from "dayjs";
import { StatsAreaChart } from "@shared/ui";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  useCommissioningAbosList,
  useCommissioningShareTypeVariationsList,
} from "@shared/api/generated/commissioning/commissioning";
import { usePaymentsChargeSchedulesIncomeByMonthList } from "@shared/api/generated/payments-—-charge-schedule/payments-—-charge-schedule";
import type { ChargeScheduleMonthlyIncome } from "@shared/api/generated/models";
import {
  buildMonthlyActiveByVariation,
  useSubscriptionVariationStats,
} from "@features/abos/hooks/useSubscriptionVariationStats";
import { buildMonthlyIncomeSeries } from "@features/abos/utils/incomeSeries";
import {
  useCurrency,
  useDateFormat,
  useDateRangePresets,
  useFiscalYearRangeState,
  useShareTypeVariationSizeOptions,
  useTenant,
} from "@hooks/index";

const { RangePicker } = DatePicker;
const { Text } = Typography;

// A finance-green, distinct from the categorical VARIATION_PALETTE (income is a
// single, non-per-variation series).
const INCOME_COLOR = "#3f8600";

interface PriceRow {
  key: string;
  name: string;
  reference: number;
  avg: number | null;
  count: number;
}

export default function DashboardAbos() {
  const { t } = useTranslation();
  const { formatCurrency } = useCurrency();
  const { dateFormat, formatDateForAPI } = useDateFormat();
  const presets = useDateRangePresets();
  const { getSetting } = useTenant();
  const { getShareTypeVariationSizeLabel } = useShareTypeVariationSizeOptions();

  // The average-vs-reference price comparison is only meaningful when members
  // can pay different amounts for the same variation — i.e. solidarity pricing.
  const allowsSolidarity = !!getSetting("allows_solidarity_pricing", false);

  // Default window: the tenant's current fiscal year (1st of
  // ``fiscal_year_start_month`` → one year).
  const [range, setRange] = useFiscalYearRangeState();

  const { data: subscriptions, isLoading } = useCommissioningAbosList({});
  // Fetched for stable per-variation labels + colours (order taken from the
  // catalogue, not from whichever subscriptions happen to exist).
  const { data: variations } = useCommissioningShareTypeVariationsList({
    physical: true,
    include_future: true,
  });

  const { variationInfo } = useSubscriptionVariationStats(
    subscriptions,
    variations,
  );

  // One line per variation: active subscription quantity per month.
  const { data: chartData, series } = useMemo(
    () => buildMonthlyActiveByVariation(subscriptions, variationInfo, range),
    [subscriptions, variationInfo, range],
  );

  // Billed income (sum of due amounts) per month, over the same range — the
  // backend aggregates it (exact Decimal SUM) so only the monthly points cross
  // the wire. Gated on ``range`` so we never fire with empty date params.
  const incomeParams = useMemo(
    () => ({
      date_from: range ? (formatDateForAPI(range[0]) ?? "") : "",
      date_to: range ? (formatDateForAPI(range[1]) ?? "") : "",
    }),
    [range, formatDateForAPI],
  );
  const { data: incomeData } = usePaymentsChargeSchedulesIncomeByMonthList(
    incomeParams,
    { query: { enabled: !!range } },
  );
  // The endpoint returns a bare array at runtime (the action isn't paginated);
  // the shared pagination-typed hook mislabels it, so cast — same pattern as
  // ChargesAbos / DecidedDeletionsCard.
  const income = useMemo(() => {
    const points = (incomeData ?? []) as unknown as ChargeScheduleMonthlyIncome[];
    return buildMonthlyIncomeSeries(points, range, {
      id: "income",
      label: t("statistics.income"),
      color: INCOME_COLOR,
    });
  }, [incomeData, range, t]);
  // Solidarity: prices actually paid per variation for subs STARTED in range.
  const paidByVar = useMemo(() => {
    const rows = subscriptions ?? [];
    const from = range ? range[0].startOf("day") : null;
    const to = range ? range[1].endOf("day") : null;
    const inRange = (validFrom: string) => {
      if (!from || !to) return true;
      const d = dayjs(validFrom);
      return !d.isBefore(from) && !d.isAfter(to);
    };
    const map = new Map<string, number[]>();
    for (const s of rows) {
      if (s.on_waiting_list || !s.valid_from || !inRange(s.valid_from))
        continue;
      const price = parseFloat(s.price_per_delivery || "0");
      if (price > 0) {
        const arr = map.get(s.share_type_variation) ?? [];
        arr.push(price);
        map.set(s.share_type_variation, arr);
      }
    }
    return map;
  }, [subscriptions, range]);

  const priceRows = useMemo<PriceRow[]>(() => {
    if (!allowsSolidarity) return [];
    return (variations ?? []).map((v) => {
      const prices = paidByVar.get(v.id ?? "") ?? [];
      const avg = prices.length
        ? prices.reduce((a, b) => a + b, 0) / prices.length
        : null;
      return {
        key: v.id ?? "",
        name: [v.share_type_name, getShareTypeVariationSizeLabel(v.size)]
          .filter(Boolean)
          .join(" · "),
        reference: parseFloat(v.active_price_per_delivery ?? "0"),
        avg,
        count: prices.length,
      };
    });
  }, [allowsSolidarity, variations, paidByVar, getShareTypeVariationSizeLabel]);

  const priceColumns = useMemo(
    () => [
      { title: t("statistics.col_variation"), dataIndex: "name", key: "name" },
      {
        title: t("statistics.col_reference_price"),
        dataIndex: "reference",
        key: "reference",
        align: "right" as const,
        render: (v: number) => formatCurrency(v),
      },
      {
        title: t("statistics.col_avg_paid"),
        dataIndex: "avg",
        key: "avg",
        align: "right" as const,
        render: (v: number | null) => (v == null ? "—" : formatCurrency(v)),
      },
    ],
    [t, formatCurrency],
  );

  return (
    <div>
      <h1>{t("statistics.abos_title")}</h1>

      <Spin spinning={isLoading}>
        <RangePicker
          value={range}
          onChange={(v) => setRange(v && v[0] && v[1] ? [v[0], v[1]] : null)}
          presets={presets}
          format={dateFormat}
          allowClear={false}
        />
        <Card
          className="dark-green-border"
          title={t("statistics.chart_active_subscriptions_by_variation")}
          style={{ marginTop: "1em" }}
        >
          <Text type="secondary">
            {t("statistics.chart_active_subscriptions_by_variation")}
          </Text>
          <StatsAreaChart
            data={chartData}
            series={series}
            height={320}
            emptyText={t("statistics.no_subscription_data")}
          />
        </Card>

        {allowsSolidarity && (
          <Card
            className="dark-green-border"
            title={t("statistics.solidarity_title")}
            style={{ marginTop: "1em" }}
          >
            <Table<PriceRow>
              size="small"
              pagination={false}
              columns={priceColumns}
              dataSource={priceRows}
              style={{ width: "40%" }}
              className="custom-jasmin-table"
              locale={{ emptyText: t("statistics.no_subscription_data") }}
            />
          </Card>
        )}

        <Card
          className="dark-green-border"
          title={t("statistics.chart_income_by_month")}
          style={{ marginTop: "1em" }}
        >
          <Text type="secondary">{t("statistics.chart_income_by_month")}</Text>
          <StatsAreaChart
            data={income.data}
            series={income.series}
            height={320}
            emptyText={t("statistics.no_income_data")}
          />
          <Typography.Paragraph
            type="secondary"
            style={{ marginTop: "0.75em", marginBottom: 0 }}
          >
            {t("statistics.income_hint")}
          </Typography.Paragraph>
        </Card>
      </Spin>
    </div>
  );
}
