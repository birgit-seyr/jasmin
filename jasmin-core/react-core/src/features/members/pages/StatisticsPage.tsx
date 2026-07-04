import { Alert, Card, Col, DatePicker, Row, Statistic, theme, Typography } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useCurrency, useDateFormat, useDateRangePresets } from "@hooks/index";

const { RangePicker } = DatePicker;

// ─────────────────────────────────────────────────────────────────────────
// SAMPLE DATA — this page is a scaffold. Everything below is deterministic
// placeholder data (no Math.random, so it's stable across re-renders). Swap
// each block for a real source when wiring up:
//   • variationsBySize  → useAllShareTypeVariations(...) grouped by `size`
//   • membersOverTime   → a members-count-by-month stats endpoint
//   • the KPI numbers   → the same endpoints' totals
// ─────────────────────────────────────────────────────────────────────────

// Share-type variations grouped by size (magnitude by ordered category).
const variationsBySize = [
  { size: "XS", count: 8 },
  { size: "S", count: 34 },
  { size: "M", count: 61 },
  { size: "L", count: 42 },
  { size: "XL", count: 19 },
];

// 24 months of cumulative member count, ending this month.
function buildMembersOverTime(): {
  monthLabel: string;
  monthMs: number;
  members: number;
}[] {
  const thisMonth = dayjs().startOf("month");
  const rows = [];
  let cumulative = 118;
  for (let i = 23; i >= 0; i--) {
    const d = thisMonth.subtract(i, "month");
    // smooth-ish deterministic growth with a gentle seasonal wiggle
    cumulative += 7 + ((i * 3) % 4) + Math.round(3 * Math.sin(i / 2));
    rows.push({
      monthLabel: d.format("MMM 'YY"),
      monthMs: d.valueOf(),
      members: cumulative,
    });
  }
  return rows;
}

export default function StatisticsPage() {
  const { t } = useTranslation();
  const { currencySymbol } = useCurrency();
  const { dateFormat } = useDateFormat();
  const presets = useDateRangePresets();
  const { token } = theme.useToken();

  const membersOverTime = useMemo(buildMembersOverTime, []);

  // Default window: the last 12 months. Drives the Zeitverlauf chart.
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(() => [
    dayjs().subtract(11, "month").startOf("month"),
    dayjs().endOf("month"),
  ]);

  const membersInRange = useMemo(() => {
    if (!range) return membersOverTime;
    const fromMs = range[0].startOf("day").valueOf();
    const toMs = range[1].endOf("day").valueOf();
    return membersOverTime.filter(
      (row) => row.monthMs >= fromMs && row.monthMs <= toMs,
    );
  }, [membersOverTime, range]);

  const totalVariations = variationsBySize.reduce((s, r) => s + r.count, 0);
  const latestMembers =
    membersOverTime[membersOverTime.length - 1]?.members ?? 0;

  // dataviz: recessive grid/axes, text in ink tokens, single-hue single-series.
  // token.* is dark-mode-aware (JasminApp switches the AntD algorithm).
  const primary = token.colorPrimary;
  const axisTick = { fill: token.colorTextSecondary, fontSize: 12 };
  const gridStroke = token.colorBorderSecondary;
  const tooltipStyle = {
    background: token.colorBgElevated,
    border: `1px solid ${token.colorBorderSecondary}`,
    borderRadius: token.borderRadius,
    boxShadow: token.boxShadowSecondary,
  } as const;
  const tooltipText = { color: token.colorText };

  return (
    <div>
      <h1>{t("statistics.title")}</h1>
      <Typography.Paragraph type="secondary" style={{ marginTop: "-0.5em" }}>
        {t("statistics.subtitle")}
      </Typography.Paragraph>

      <Alert
        type="info"
        showIcon
        message={t("statistics.sample_notice")}
        style={{ marginBottom: "1em" }}
      />

      {/* KPI row — hero numbers (dataviz: sometimes the answer is a stat tile) */}
      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}>
          <Card>
            <Statistic
              title={t("statistics.kpi_members")}
              value={latestMembers}
              valueStyle={{ color: primary }}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic
              title={t("statistics.kpi_active_subscriptions")}
              value={289}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic
              title={t("statistics.kpi_variations")}
              value={totalVariations}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic
              title={t("statistics.kpi_avg_price")}
              value={18.5}
              precision={2}
              suffix={currencySymbol}
            />
          </Card>
        </Col>
      </Row>

      {/* Charts row */}
      <Row gutter={[16, 16]} style={{ marginTop: "1em" }}>
        {/* Magnitude by ordered category → bars, single hue */}
        <Col xs={24} lg={12}>
          <Card title={t("statistics.chart_variations_by_size")}>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart
                data={variationsBySize}
                margin={{ top: 8, right: 8, left: -12, bottom: 0 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke={gridStroke}
                  vertical={false}
                />
                <XAxis
                  dataKey="size"
                  tick={axisTick}
                  axisLine={{ stroke: gridStroke }}
                  tickLine={false}
                />
                <YAxis
                  tick={axisTick}
                  axisLine={false}
                  tickLine={false}
                  width={32}
                  allowDecimals={false}
                />
                <Tooltip
                  cursor={{ fill: token.colorFillSecondary }}
                  contentStyle={tooltipStyle}
                  labelStyle={tooltipText}
                  itemStyle={tooltipText}
                />
                <Bar
                  dataKey="count"
                  name={t("statistics.series_variations")}
                  fill={primary}
                  radius={[4, 4, 0, 0]}
                  maxBarSize={52}
                />
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </Col>

        {/* Change over time → area, single hue; RangePicker filters the window */}
        <Col xs={24} lg={12}>
          <Card
            title={t("statistics.chart_members_over_time")}
            extra={
              <RangePicker
                value={range}
                onChange={(v) =>
                  setRange(v && v[0] && v[1] ? [v[0], v[1]] : null)
                }
                presets={presets}
                format={dateFormat}
                allowClear={false}
              />
            }
          >
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart
                data={membersInRange}
                margin={{ top: 8, right: 8, left: -12, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="membersFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={primary} stopOpacity={0.28} />
                    <stop offset="100%" stopColor={primary} stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke={gridStroke}
                  vertical={false}
                />
                <XAxis
                  dataKey="monthLabel"
                  tick={axisTick}
                  axisLine={{ stroke: gridStroke }}
                  tickLine={false}
                  minTickGap={16}
                />
                <YAxis
                  tick={axisTick}
                  axisLine={false}
                  tickLine={false}
                  width={40}
                  allowDecimals={false}
                />
                <Tooltip
                  contentStyle={tooltipStyle}
                  labelStyle={tooltipText}
                  itemStyle={tooltipText}
                />
                <Area
                  type="monotone"
                  dataKey="members"
                  name={t("statistics.series_members")}
                  stroke={primary}
                  strokeWidth={2}
                  fill="url(#membersFill)"
                  dot={false}
                  activeDot={{ r: 4 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
